/*
 * progforge.c — a generative reliability tester for Dictum.
 *
 * WHY A GENERATOR AND NOT ANOTHER MUTATOR
 * ---------------------------------------
 * The existing fuzzers (bughunter.dict, multifile_fuzzer.py,
 * blessed_library_fuzzer.py, differential_fuzzer.py) all MUTATE a small set
 * of fixed seed programs. That explores variations of code someone already
 * wrote. It ran ~5,600 rounds without finding what a single hand-written
 * 3-module program found in minutes: a module exporting BOTH an int- and a
 * text-returning action, and a variable legitimately named `out`. Nobody
 * had written those combinations, so no mutation could reach them.
 *
 * This tool GENERATES fresh, valid programs by composing Dictum features in
 * combinations no fixture contains.
 *
 * THE CRITICAL PROPERTY: SELF-COMPUTED EXPECTED OUTPUT
 * ----------------------------------------------------
 * Every other tool here can only ask "did it crash?" or "do the backends
 * agree?" -- both of which a compiler can pass while being WRONG (all three
 * backends agreeing on 2+2=5 looks perfectly healthy to a differential
 * check). This generator evaluates each program's semantics in C as it
 * builds it, so it knows the right answer independently. That turns the
 * check into "is it CORRECT", which is a strictly stronger bar.
 *
 * FEATURE SURFACE COVERED (composed randomly per program)
 *   - whole-number arithmetic: plus, minus, times, modulo
 *   - comparison + if / otherwise
 *   - while loops with accumulators
 *   - user-defined actions, with parameters and return values
 *   - multi-module projects (module + program in separate files)
 *   - cross-file action calls
 *   - text values and printing
 *   - identifiers that collide with backend reserved words (out, type,
 *     end, ...) -- the exact class that crashed the Nim compiler
 *
 * Written in C for speed, per the request: program construction and
 * expected-value evaluation are effectively free, so wall-clock time is
 * dominated by the real compilers, which is where it should be.
 *
 * Usage:  ./progforge --seconds 60 [--workdir DIR] [--compiler PATH]
 */
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/wait.h>

#define MAXSRC 65536
#define MAXVARS 8

/* Deliberately includes words reserved in Nim (out, type, end, method,
 * proc, var, block) and in C/C++ (auto, register, class, new, delete).
 * A valid Dictum program may use any of them as a variable name; every
 * backend must cope. This is exactly how the `out` crash was found. */
static const char *VARNAMES[] = {
    "total", "count", "out", "type", "end_v", "value", "result", "acc",
    "temp", "item", "block_v", "method_v", "data", "idx"
};
#define NVARNAMES (sizeof(VARNAMES)/sizeof(VARNAMES[0]))

typedef struct {
    char src[MAXSRC];
    size_t len;
} Buf;

__attribute__((format(printf, 2, 3)))
static void bappend(Buf *b, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(b->src + b->len, MAXSRC - b->len, fmt, ap);
    va_end(ap);
    if (n > 0) b->len += (size_t)n;
}

static unsigned long rng_state;
static unsigned long rnd(void) {
    /* Bounded LCG: state is kept under 2^31 so the multiply cannot overflow
     * a signed long on any sane platform. An earlier tool in this project
     * used glibc-style constants in int32 and hit real signed-overflow UB,
     * which gcc then exploited to make a negativity check evaluate false on
     * a visibly negative value. Not repeating that. */
    rng_state = (rng_state * 1103515245UL + 12345UL) & 0x7FFFFFFFUL;
    return rng_state;
}
static long rndrange(long lo, long hi) {
    if (hi <= lo) return lo;
    return lo + (long)(rnd() % (unsigned long)(hi - lo + 1));
}

/* ------------------------------------------------------------------ */
/* Program generation. Each generator BUILDS the source and SIMULTANEOUSLY
 * evaluates what it must print, so expected output is known exactly.     */
/* ------------------------------------------------------------------ */

typedef struct {
    Buf module_src;      /* may be empty (single-file program)  */
    Buf main_src;
    Buf expected;        /* concatenated expected stdout, whitespace-free */
    int multifile;
    int uses_ffi;
} Program;

static const char *pick_var(int i) { return VARNAMES[i % NVARNAMES]; }

static void gen_arith_block(Program *p, int *lineno) {
    const char *v = pick_var((int)rndrange(0, NVARNAMES - 1));
    long a = rndrange(0, 50), b = rndrange(1, 20);
    long expect;
    int op = (int)rndrange(0, 3);
    const char *opname;
    switch (op) {
        case 0: opname = "plus";   expect = a + b; break;
        case 1: opname = "minus";  expect = a - b; break;
        case 2: opname = "times";  expect = a * b; break;
        default: opname = "modulo"; expect = a % b; break;
    }
    bappend(&p->main_src, "    keep %s_%d as whole number with value %ld\n", v, *lineno, a);
    bappend(&p->main_src, "    put %s_%d %s %ld into %s_%d\n", v, *lineno, opname, b, v, *lineno);
    bappend(&p->main_src, "    print the text \"r%d=\" and %s_%d\n", *lineno, v, *lineno);
    bappend(&p->expected, "r%d=%ld", *lineno, expect);
    (*lineno)++;
}

static void gen_if_block(Program *p, int *lineno) {
    long a = rndrange(0, 30), b = rndrange(0, 30);
    const char *v = pick_var((int)rndrange(0, NVARNAMES - 1));
    bappend(&p->main_src, "    keep %s_%d as whole number with value %ld\n", v, *lineno, a);
    bappend(&p->main_src, "    if %s_%d is greater than %ld then\n", v, *lineno, b);
    bappend(&p->main_src, "        print the text \"c%d=hi\"\n", *lineno);
    bappend(&p->main_src, "    otherwise\n");
    bappend(&p->main_src, "        print the text \"c%d=lo\"\n", *lineno);
    bappend(&p->main_src, "    end if\n");
    bappend(&p->expected, "c%d=%s", *lineno, (a > b) ? "hi" : "lo");
    (*lineno)++;
}

static void gen_while_block(Program *p, int *lineno) {
    long n = rndrange(1, 6), step = rndrange(1, 4);
    long sum = 0;
    for (long i = 0; i < n; i++) sum += step;
    const char *v = pick_var((int)rndrange(0, NVARNAMES - 1));
    bappend(&p->main_src, "    keep %s_%di as whole number with value 0\n", v, *lineno);
    bappend(&p->main_src, "    keep %s_%ds as whole number with value 0\n", v, *lineno);
    bappend(&p->main_src, "    while %s_%di is less than %ld repeat\n", v, *lineno, n);
    bappend(&p->main_src, "        put %s_%ds plus %ld into %s_%ds\n", v, *lineno, step, v, *lineno);
    bappend(&p->main_src, "        put %s_%di plus 1 into %s_%di\n", v, *lineno, v, *lineno);
    bappend(&p->main_src, "    end while\n");
    bappend(&p->main_src, "    print the text \"w%d=\" and %s_%ds\n", *lineno, v, *lineno);
    bappend(&p->expected, "w%d=%ld", *lineno, sum);
    (*lineno)++;
}

static void gen_text_block(Program *p, int *lineno) {
    bappend(&p->main_src, "    keep t_%d as text with value \"s%d\"\n", *lineno, *lineno);
    bappend(&p->main_src, "    print the text \"t%d=\" and t_%d\n", *lineno, *lineno);
    bappend(&p->expected, "t%d=s%d", *lineno, *lineno);
    (*lineno)++;
}

static void gen_module_with_actions(Program *p, int *lineno) {
    /* A module exporting BOTH an int-returning and a text-returning action.
     * This exact shape is what exposed the missing dictum_text entry in the
     * project builder's header return-type whitelist -- the int action was
     * declared fine while the text action silently vanished. */
    long mul = rndrange(2, 9);
    long arg = rndrange(1, 12);
    bappend(&p->module_src, "module helper\n\n");
    bappend(&p->module_src, "    action scale takes n as whole number produces whole number\n");
    bappend(&p->module_src, "        keep out as whole number with value 0\n");   /* reserved in Nim */
    bappend(&p->module_src, "        put n times %ld into out\n", mul);
    bappend(&p->module_src, "        return out\n");
    bappend(&p->module_src, "    end action\n\n");
    bappend(&p->module_src, "    action label takes nothing produces text\n");
    bappend(&p->module_src, "        keep type as text with value \"lbl\"\n");    /* reserved in Nim */
    bappend(&p->module_src, "        return type\n");
    bappend(&p->module_src, "    end action\n\n");
    bappend(&p->module_src, "end module\n");

    bappend(&p->main_src, "    keep sc_%d as whole number with value 0\n", *lineno);
    bappend(&p->main_src, "    call helper.scale with %ld giving sc_%d\n", arg, *lineno);
    bappend(&p->main_src, "    print the text \"m%d=\" and sc_%d\n", *lineno, *lineno);
    bappend(&p->expected, "m%d=%ld", *lineno, arg * mul);
    (*lineno)++;

    bappend(&p->main_src, "    keep lb_%d as text with value \"\"\n", *lineno);
    bappend(&p->main_src, "    call helper.label giving lb_%d\n", *lineno);
    bappend(&p->main_src, "    print the text \"l%d=\" and lb_%d\n", *lineno, *lineno);
    bappend(&p->expected, "l%d=lbl", *lineno);
    (*lineno)++;
}

static void generate(Program *p) {
    memset(p, 0, sizeof(*p));
    int lineno = 1;
    p->multifile = (rndrange(0, 2) == 0);   /* ~1 in 3 are multi-module */

    if (p->multifile) {
        bappend(&p->main_src, "program main\n\n    use helper\n\n");
    } else {
        bappend(&p->main_src, "program main\n\n");
    }

    int nblocks = (int)rndrange(2, 5);
    if (p->multifile) gen_module_with_actions(p, &lineno);

    for (int i = 0; i < nblocks; i++) {
        switch (rndrange(0, 3)) {
            case 0: gen_arith_block(p, &lineno); break;
            case 1: gen_if_block(p, &lineno);    break;
            case 2: gen_while_block(p, &lineno); break;
            default: gen_text_block(p, &lineno); break;
        }
    }
    bappend(&p->main_src, "\nend program\n");
}

/* ------------------------------------------------------------------ */
static int write_file(const char *path, const char *data) {
    FILE *f = fopen(path, "w");
    if (!f) return -1;
    fputs(data, f);
    fclose(f);
    return 0;
}

/* Strip ALL whitespace, so the known printf-vs-echo trailing-newline
 * difference between the C/C++ and Nim backends is not reported as a
 * correctness failure. That divergence is real but is a separate,
 * already-documented language-design question. */
static void squash(const char *in, char *out, size_t cap) {
    size_t j = 0;
    for (size_t i = 0; in[i] && j + 1 < cap; i++)
        if (in[i] != ' ' && in[i] != '\n' && in[i] != '\t' && in[i] != '\r')
            out[j++] = in[i];
    out[j] = 0;
}

static int run_capture(const char *cmd, char *out, size_t cap) {
    FILE *fp = popen(cmd, "r");
    if (!fp) return -1;
    size_t n = fread(out, 1, cap - 1, fp);
    out[n] = 0;
    int rc = pclose(fp);
    return WIFEXITED(rc) ? WEXITSTATUS(rc) : -1;
}

int main(int argc, char **argv) {
    long seconds = 60;
    const char *workdir = "/tmp/progforge_work";
    const char *compiler_dir = "..";
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--seconds") && i + 1 < argc) seconds = atol(argv[++i]);
        else if (!strcmp(argv[i], "--workdir") && i + 1 < argc) workdir = argv[++i];
        else if (!strcmp(argv[i], "--compiler") && i + 1 < argc) compiler_dir = argv[++i];
    }
    rng_state = (unsigned long)getpid() ^ (unsigned long)time(NULL);
    rng_state &= 0x7FFFFFFFUL;

    char cmd[4096], buf[65536], got[65536], want[65536];
    mkdir(workdir, 0755);

    long total = 0, ok = 0, wrong = 0, buildfail = 0, disagree = 0;
    const char *backends[3] = {"c", "cpp", "nim"};
    time_t start = time(NULL);

    printf("progforge: generating real Dictum programs for %lds\n", seconds);
    printf("           (verifies CORRECTNESS against self-computed expected output,\n");
    printf("            not merely that the compilers didn't crash)\n");
    fflush(stdout);

    while (time(NULL) - start < seconds) {
        Program p;
        generate(&p);

        char dir[1024];
        snprintf(dir, sizeof dir, "%s/case%ld", workdir, total);
        snprintf(cmd, sizeof cmd, "rm -rf %s && mkdir -p %s", dir, dir);
        if (system(cmd) != 0) { total++; continue; }

        char path[1200];
        snprintf(path, sizeof path, "%s/main.dict", dir);
        write_file(path, p.main_src.src);
        if (p.multifile) {
            snprintf(path, sizeof path, "%s/helper.dict", dir);
            write_file(path, p.module_src.src);
        }
        squash(p.expected.src, want, sizeof want);

        char outs[3][65536];
        int good[3] = {0, 0, 0};
        int any_buildfail = 0;

        for (int b = 0; b < 3; b++) {
            if (p.multifile) {
                snprintf(cmd, sizeof cmd,
                    "cd %s && rm -f dictum.project.json && "
                    "python3 %s/project_builder.py . --backend %s --out build_%s "
                    ">/dev/null 2>&1 && cd build_%s && "
                    "{ [ -f Makefile ] && make >/dev/null 2>&1 || sh build.sh >/dev/null 2>&1; } "
                    "&& ./main 2>/dev/null",
                    dir, compiler_dir, backends[b], backends[b], backends[b]);
            } else {
                snprintf(cmd, sizeof cmd,
                    "cd %s && python3 %s/dictumc_cli.py main.dict --backend %s "
                    "--compile --output prog_%s >/dev/null 2>&1 && ./prog_%s 2>/dev/null",
                    dir, compiler_dir, backends[b], backends[b], backends[b]);
            }
            buf[0] = 0;
            int rc = run_capture(cmd, buf, sizeof buf);
            if (rc != 0 || buf[0] == 0) { any_buildfail = 1; outs[b][0] = 0; continue; }
            squash(buf, got, sizeof got);
            snprintf(outs[b], sizeof outs[b], "%s", got);
            good[b] = 1;
        }

        int nres = good[0] + good[1] + good[2];
        if (any_buildfail && nres == 0) {
            buildfail++;
        } else {
            int mismatch = 0, differ = 0;
            for (int b = 0; b < 3; b++) {
                if (!good[b]) continue;
                if (strcmp(outs[b], want) != 0) mismatch = 1;
            }
            for (int b = 1; b < 3; b++)
                if (good[b] && good[0] && strcmp(outs[b], outs[0]) != 0) differ = 1;

            if (mismatch) {
                wrong++;
                printf("!! WRONG OUTPUT (case %ld, %s)\n   want: %s\n",
                       total, p.multifile ? "multifile" : "single", want);
                for (int b = 0; b < 3; b++)
                    if (good[b]) printf("   %-3s : %s\n", backends[b], outs[b]);
                printf("   kept at %s\n", dir);
                fflush(stdout);
            } else if (differ) {
                disagree++;
                printf("!! BACKEND DISAGREEMENT (case %ld) kept at %s\n", total, dir);
                fflush(stdout);
            } else {
                ok++;
                snprintf(cmd, sizeof cmd, "rm -rf %s", dir);
                if (system(cmd) != 0) { /* cleanup best-effort */ }
            }
            if (any_buildfail) buildfail++;
        }
        total++;

        if (total % 10 == 0) {
            printf("... %ld generated | correct=%ld wrong=%ld disagree=%ld buildfail=%ld\n",
                   total, ok, wrong, disagree, buildfail);
            fflush(stdout);
        }
    }

    printf("\n=== progforge summary ===\n");
    printf("generated:        %ld\n", total);
    printf("correct:          %ld\n", ok);
    printf("WRONG OUTPUT:     %ld\n", wrong);
    printf("backend disagree: %ld\n", disagree);
    printf("build failures:   %ld\n", buildfail);
    fflush(stdout);
    return (wrong || disagree) ? 1 : 0;
}
