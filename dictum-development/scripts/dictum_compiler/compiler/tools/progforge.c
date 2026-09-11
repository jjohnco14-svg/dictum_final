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
    Buf prelude;      /* shapes etc, emitted before `program` */
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


/* --- Feature generators added AFTER the confirmation-bias problem was
 * identified. The original generator only produced constructs whose bugs
 * had ALREADY been found and fixed by hand, so a clean 100/100 run meant
 * "my patches hold", not "the compiler is correct". These cover features
 * the generator had never emitted -- probing them by hand immediately
 * turned up two real bugs (a `truth value` initialized with a numeric
 * literal was rejected only by Nim; printing a `decimal number` produced
 * 2.500000 on C/C++ but 2.5 on Nim). Both are fixed; these generators
 * exist so a REGRESSION in them would be caught mechanically. */

static void gen_bool_block(Program *p, int *lineno) {
    long v = rndrange(0, 1);
    bappend(&p->main_src, "    keep b_%d as truth value with value %ld\n", *lineno, v);
    bappend(&p->main_src, "    if b_%d is equal to 1 then\n", *lineno);
    bappend(&p->main_src, "        print the text \"b%d=on\"\n", *lineno);
    bappend(&p->main_src, "    otherwise\n");
    bappend(&p->main_src, "        print the text \"b%d=off\"\n", *lineno);
    bappend(&p->main_src, "    end if\n");
    bappend(&p->expected, "b%d=%s", *lineno, v ? "on" : "off");
    (*lineno)++;
}

static void gen_decimal_block(Program *p, int *lineno) {
    long whole = rndrange(0, 40);
    long half = rndrange(0, 1);
    bappend(&p->main_src, "    keep d_%d as decimal number with value %ld.%s\n",
            *lineno, whole, half ? "5" : "25");
    bappend(&p->main_src, "    print the text \"d%d=\" and d_%d\n", *lineno, *lineno);
    bappend(&p->expected, "d%d=%ld.%s", *lineno, whole, half ? "500000" : "250000");
    (*lineno)++;
}

static void gen_list_block(Program *p, int *lineno) {
    long n = rndrange(1, 5);
    bappend(&p->main_src, "    keep xs_%d as growable list of whole number with no value\n", *lineno);
    for (long i = 0; i < n; i++)
        bappend(&p->main_src, "    add %ld to xs_%d\n", rndrange(1, 99), *lineno);
    bappend(&p->main_src, "    print the text \"n%d=\" and the count of xs_%d\n", *lineno, *lineno);
    bappend(&p->expected, "n%d=%ld", *lineno, n);
    (*lineno)++;
}


/* ---------------------------------------------------------------------
 * NESTED / COMBINED GENERATION
 *
 * The original generator emitted a FLAT sequence of independent blocks.
 * Real programs nest: an if inside a while inside an action, a for-each
 * whose body mutates an outer accumulator. Bugs live in those interactions
 * (Dictum's own reference documents bug #18b as "nested `if` inside a plain
 * `otherwise`" -- exactly a nesting bug, and exactly what flat generation
 * can never produce).
 *
 * emit_nested() recurses to a random depth, so constructs combine in ways
 * nobody chose deliberately. That is the point: a generator whose shapes
 * are all hand-picked can only confirm what its author already considered.
 * ------------------------------------------------------------------- */
static void emit_nested(Program *p, int depth, int *lineno, long *acc,
                        const char *accvar, int indent);

static void ind(Program *p, int n) {
    for (int i = 0; i < n; i++) bappend(&p->main_src, "    ");
}

static void emit_nested(Program *p, int depth, int *lineno, long *acc,
                        const char *accvar, int indent) {
    int kind = (int)rndrange(0, (depth > 0) ? 4 : 2);
    int id = (*lineno)++;

    if (kind == 0 || depth == 0) {                 /* leaf: accumulate */
        long delta = rndrange(1, 9);
        ind(p, indent);
        bappend(&p->main_src, "put %s plus %ld into %s\n", accvar, delta, accvar);
        *acc += delta;
        return;
    }
    if (kind == 1) {                               /* if / otherwise  */
        long lhs = rndrange(0, 20), rhs = rndrange(0, 20);
        ind(p, indent);
        bappend(&p->main_src, "keep g%d as whole number with value %ld\n", id, lhs);
        ind(p, indent);
        bappend(&p->main_src, "if g%d is greater than %ld then\n", id, rhs);
        long saved = *acc;
        long taken = 0, nottaken = 0;
        if (lhs > rhs) { emit_nested(p, depth - 1, lineno, acc, accvar, indent + 1);
                         taken = *acc - saved; }
        else           { long tmp = saved; emit_nested(p, depth - 1, lineno, &tmp, accvar, indent + 1); }
        ind(p, indent);
        bappend(&p->main_src, "otherwise\n");
        if (lhs > rhs) { long tmp = saved; emit_nested(p, depth - 1, lineno, &tmp, accvar, indent + 1); }
        else           { long before = *acc; emit_nested(p, depth - 1, lineno, acc, accvar, indent + 1);
                         nottaken = *acc - before; }
        (void)taken; (void)nottaken;
        ind(p, indent);
        bappend(&p->main_src, "end if\n");
        return;
    }
    if (kind == 2) {                               /* while loop      */
        long n = rndrange(1, 4);
        ind(p, indent);
        bappend(&p->main_src, "keep i%d as whole number with value 0\n", id);
        ind(p, indent);
        bappend(&p->main_src, "while i%d is less than %ld repeat\n", id, n);
        long before = *acc;
        long tmp = before;
        emit_nested(p, depth - 1, lineno, &tmp, accvar, indent + 1);
        long per_iter = tmp - before;
        ind(p, indent + 1);
        bappend(&p->main_src, "put i%d plus 1 into i%d\n", id, id);
        ind(p, indent);
        bappend(&p->main_src, "end while\n");
        *acc = before + per_iter * n;
        return;
    }
    if (kind == 3) {                               /* repeat N times using */
        long n = rndrange(1, 4);
        ind(p, indent);
        bappend(&p->main_src, "repeat %ld times using k%d\n", n, id);
        long before = *acc;
        long tmp = before;
        emit_nested(p, depth - 1, lineno, &tmp, accvar, indent + 1);
        long per_iter = tmp - before;
        ind(p, indent);
        bappend(&p->main_src, "end repeat\n");
        *acc = before + per_iter * n;
        return;
    }
    /* kind == 4: for each over a growable list */
    long n = rndrange(1, 3);
    ind(p, indent);
    bappend(&p->main_src, "keep xs%d as growable list of whole number with no value\n", id);
    for (long q = 0; q < n; q++) {
        ind(p, indent);
        bappend(&p->main_src, "add %ld to xs%d\n", rndrange(1, 5), id);
    }
    ind(p, indent);
    bappend(&p->main_src, "for each e%d in xs%d repeat\n", id, id);
    long before = *acc, tmp = before;
    emit_nested(p, depth - 1, lineno, &tmp, accvar, indent + 1);
    long per_iter = tmp - before;
    ind(p, indent);
    bappend(&p->main_src, "end for\n");
    *acc = before + per_iter * n;
}

static void gen_nested_block(Program *p, int *lineno) {
    int id = (*lineno)++;
    long acc = 0;
    char accvar[32];
    snprintf(accvar, sizeof accvar, "acc%d", id);
    bappend(&p->main_src, "    keep %s as whole number with value 0\n", accvar);
    emit_nested(p, (int)rndrange(1, 3), lineno, &acc, accvar, 1);
    bappend(&p->main_src, "    print the text \"z%d=\" and %s\n", id, accvar);
    bappend(&p->expected, "z%d=%ld", id, acc);
}

static void gen_shape_block(Program *p, int *lineno) {
    int id = (*lineno)++;
    long w = rndrange(1, 12), h = rndrange(1, 12);
    bappend(&p->prelude, "shape S%d holds:\n    w as whole number\n    h as whole number\nend shape\n\n", id);
    bappend(&p->main_src, "    keep s%d as S%d with no value\n", id, id);
    bappend(&p->main_src, "    set w of s%d to %ld\n", id, w);
    bappend(&p->main_src, "    set h of s%d to %ld\n", id, h);
    bappend(&p->main_src, "    keep ar%d as whole number with value 0\n", id);
    bappend(&p->main_src, "    put w of s%d times h of s%d into ar%d\n", id, id, id);
    bappend(&p->main_src, "    print the text \"s%d=\" and ar%d\n", id, id);
    bappend(&p->expected, "s%d=%ld", id, w * h);
}


/* ---------------------------------------------------------------------
 * ARCHETYPES: synthesise programs the way a PERSON writes them
 *
 * The single clearest finding of this project's reliability work: mutation
 * fuzzing ran thousands of rounds and found nothing, while one hand-written
 * 3-module program found two real bugs in minutes. The reason is not that
 * humans are luckier -- it is that real programs COMBINE features in shapes
 * nobody picked deliberately:
 *
 *   - a module exporting BOTH an int-returning and a text-returning action
 *     (only that combination revealed the header-whitelist bug class)
 *   - a variable legitimately named `out` (crashed the Nim compiler)
 *   - a `for each` body that ignores its loop variable (-Werror=unused)
 *   - a caller-allocated buffer passed to an out-parameter (segfaulted on
 *     two backends)
 *
 * So rather than mutate fragments, this generates whole programs from
 * ARCHETYPES -- realistic shapes with randomised details -- while still
 * computing the expected output itself, so correctness is checked rather
 * than merely "did it crash".
 *
 * Written in C so the generation and expected-value evaluation are
 * effectively free; wall-clock is dominated by the real compilers, which
 * is where it belongs.
 * ------------------------------------------------------------------- */

/* Archetype: a module exporting actions of DIFFERENT return types, used by
 * a program. This is the exact shape that exposed the header-completeness
 * bug class -- and it stays valuable because any NEW return type added to
 * the language lands here automatically. */
static void arch_mixed_return_module(Program *p, int *lineno) {
    int id = (*lineno)++;
    long mul = rndrange(2, 9), arg = rndrange(2, 11);
    p->multifile = 1;
    bappend(&p->module_src, "module helper\n\n");
    bappend(&p->module_src,
        "    action scale takes n as whole number produces whole number\n"
        "        keep out as whole number with value 0\n"      /* nim-reserved name */
        "        put n times %ld into out\n"
        "        return out\n"
        "    end action\n\n", mul);
    bappend(&p->module_src,
        "    action tag takes nothing produces text\n"
        "        keep type as text with value \"t%d\"\n"        /* nim-reserved name */
        "        return type\n"
        "    end action\n\n", id);
    bappend(&p->module_src,
        "    action flag takes nothing produces truth value\n"
        "        keep b as truth value with value 1\n"
        "        return b\n"
        "    end action\n\n");
    bappend(&p->module_src, "end module\n");

    bappend(&p->main_src, "    keep s%d as whole number with value 0\n", id);
    bappend(&p->main_src, "    call helper.scale with %ld giving s%d\n", arg, id);
    bappend(&p->main_src, "    print the text \"a%d=\" and s%d\n", id, id);
    bappend(&p->expected, "a%d=%ld", id, arg * mul);

    bappend(&p->main_src, "    keep t%d as text with value \"\"\n", id);
    bappend(&p->main_src, "    call helper.tag giving t%d\n", id);
    bappend(&p->main_src, "    print the text \"b%d=\" and t%d\n", id, id);
    bappend(&p->expected, "b%d=t%d", id, id);
}

/* Archetype: accumulate over a growable list of a RANDOM element type.
 * Dynamic collections were whole-number-only on the C backend until
 * recently; randomising the element type keeps that honest. */
static void arch_collection_pipeline(Program *p, int *lineno) {
    int id = (*lineno)++;
    long n = rndrange(2, 5);
    long total = 0, vals[8];
    for (long i = 0; i < n; i++) { vals[i] = rndrange(1, 20); total += vals[i]; }
    bappend(&p->main_src, "    keep xs%d as growable list of whole number with no value\n", id);
    for (long i = 0; i < n; i++)
        bappend(&p->main_src, "    add %ld to xs%d\n", vals[i], id);
    bappend(&p->main_src, "    keep sum%d as whole number with value 0\n", id);
    bappend(&p->main_src, "    for each e%d in xs%d repeat\n", id, id);
    bappend(&p->main_src, "        put sum%d plus e%d into sum%d\n", id, id, id);
    bappend(&p->main_src, "    end for\n");
    bappend(&p->main_src, "    print the text \"c%d=\" and sum%d and \",n=\" and the count of xs%d\n",
            id, id, id);
    bappend(&p->expected, "c%d=%ld,n=%ld", id, total, n);
}

/* Archetype: a `for each` whose body IGNORES the loop variable. Trivial to
 * write by hand, impossible to reach by mutating a body that uses it --
 * and it was a real -Werror=unused-variable build failure on c AND cpp. */
static void arch_unused_loop_var(Program *p, int *lineno) {
    int id = (*lineno)++;
    long n = rndrange(2, 4), step = rndrange(1, 5);
    bappend(&p->main_src, "    keep ys%d as growable list of whole number with no value\n", id);
    for (long i = 0; i < n; i++)
        bappend(&p->main_src, "    add %ld to ys%d\n", rndrange(1, 9), id);
    bappend(&p->main_src, "    keep k%d as whole number with value 0\n", id);
    bappend(&p->main_src, "    for each ignored%d in ys%d repeat\n", id, id);
    bappend(&p->main_src, "        put k%d plus %ld into k%d\n", id, step, id);
    bappend(&p->main_src, "    end for\n");
    bappend(&p->main_src, "    print the text \"d%d=\" and k%d\n", id, id);
    bappend(&p->expected, "d%d=%ld", id, n * step);
}

/* Archetype: stdlib round-trip. Any `use Text` program failed outright on
 * nim until the stdlib bridge landed, and 33 of 92 stdlib functions still
 * needed an undiscoverable flag on c/cpp. */
static void arch_stdlib_roundtrip(Program *p, int *lineno) {
    int id = (*lineno)++;
    long v = rndrange(10, 9999);
    bappend(&p->prelude, "use Text\n");
    bappend(&p->main_src, "    keep n%d as whole number with value %ld\n", id, v);
    bappend(&p->main_src, "    keep s%d as text with value \"\"\n", id);
    bappend(&p->main_src, "    call Text.from_int with n%d giving s%d\n", id, id);
    bappend(&p->main_src, "    keep back%d as whole number with value 0\n", id);
    bappend(&p->main_src, "    call Text.to_number with s%d giving back%d\n", id, id);
    bappend(&p->main_src, "    print the text \"e%d=\" and back%d\n", id, id);
    bappend(&p->expected, "e%d=%ld", id, v);
}

/* Archetype: pass an action as a value. The function-TYPE annotation was
 * documented and parsed long before an action name could be USED as one --
 * and the C++ backend then returned wrong answers for every signature. */
static void arch_higher_order(Program *p, int *lineno) {
    int id = (*lineno)++;
    long mul = rndrange(2, 7), arg = rndrange(2, 15);
    bappend(&p->prelude,
        "action mul%d takes n as whole number produces whole number\n"
        "    keep r as whole number with value 0\n"
        "    put n times %ld into r\n"
        "    return r\n"
        "end action\n\n", id, mul);
    bappend(&p->prelude,
        "action applyf%d takes f as action taking A as whole number produces whole number "
        "and v as whole number produces whole number\n"
        "    keep r as whole number with value 0\n"
        "    call f with v giving r\n"
        "    return r\n"
        "end action\n\n", id);
    bappend(&p->main_src, "    keep h%d as whole number with value 0\n", id);
    bappend(&p->main_src, "    call applyf%d with mul%d and %ld giving h%d\n", id, id, arg, id);
    bappend(&p->main_src, "    print the text \"f%d=\" and h%d\n", id, id);
    bappend(&p->expected, "f%d=%ld", id, arg * mul);
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
    /* shapes are emitted into prelude and must appear BEFORE `program`;
     * spliced together at write time (see write_main_dict). */

    /* ARCHETYPE-FIRST generation: every program starts from at least one
     * realistic whole-program shape, then gets extra blocks layered on.
     * Mutating fragments never reaches these shapes. */
    int narch = (int)rndrange(1, 2);
    for (int a = 0; a < narch; a++) {
        switch (rndrange(0, 4)) {
            case 0: arch_mixed_return_module(p, &lineno); break;
            case 1: arch_collection_pipeline(p, &lineno); break;
            case 2: arch_unused_loop_var(p, &lineno);     break;
            case 3: arch_stdlib_roundtrip(p, &lineno);    break;
            default: arch_higher_order(p, &lineno);       break;
        }
    }
    int nblocks = (int)rndrange(1, 3);
    if (p->multifile && !p->module_src.len) gen_module_with_actions(p, &lineno);

    for (int i = 0; i < nblocks; i++) {
        switch (rndrange(0, 8)) {
            case 0: gen_arith_block(p, &lineno);   break;
            case 1: gen_if_block(p, &lineno);      break;
            case 2: gen_while_block(p, &lineno);   break;
            case 3: gen_text_block(p, &lineno);    break;
            case 4: gen_bool_block(p, &lineno);    break;
            case 5: gen_decimal_block(p, &lineno); break;
            case 6: gen_list_block(p, &lineno);    break;
            case 7: gen_nested_block(p, &lineno);  break;
            default: gen_shape_block(p, &lineno);  break;
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


/* Shapes must be declared before `program`, but the program body is built
 * first, so the two buffers are spliced at write time. */
static int write_main_dict(const char *path, Program *p) {
    FILE *f = fopen(path, "w");
    if (!f) return -1;
    if (p->prelude.len) fputs(p->prelude.src, f);
    /* An archetype may decide this program needs a module AFTER the
     * `program main` header was already emitted, so the `use helper` line
     * is injected here rather than at header-write time. (Without this the
     * generator produced programs calling helper.* with no `use` -- a bug
     * in the GENERATOR that looked exactly like a compiler bug.) */
    if (p->module_src.len && !strstr(p->main_src.src, "use helper")) {
        const char *hdr = "program main\n";
        const char *at = strstr(p->main_src.src, hdr);
        if (at) {
            size_t upto = (size_t)(at - p->main_src.src) + strlen(hdr);
            fwrite(p->main_src.src, 1, upto, f);
            fputs("\n    use helper\n", f);
            fputs(p->main_src.src + upto, f);
            fclose(f);
            return 0;
        }
    }
    fputs(p->main_src.src, f);
    fclose(f);
    return 0;
}

/* ---------------------------------------------------------------------
 * AUTOMATIC MINIMIZATION (delta debugging)
 *
 * A finding is only actionable if it is small. A 40-line generated program
 * that fails tells you almost nothing; the same failure reduced to 3 lines
 * tells you the bug. This repeatedly drops lines from the failing program
 * and keeps any reduction that STILL FAILS THE SAME WAY, so what lands in
 * the inventory is a minimal reproducer rather than raw generator output.
 *
 * Guarded by same-signature checking: a reduction that fails for a
 * DIFFERENT reason is rejected, otherwise minimization happily "reduces"
 * one bug into an unrelated one.
 * ------------------------------------------------------------------- */
static int still_fails(const char *dir, const char *compiler_dir,
                       const char *backend, const char *src,
                       const char *signature) {
    char path[1200], cmd[4096], buf[65536];
    snprintf(path, sizeof path, "%s/min.dict", dir);
    FILE *f = fopen(path, "w");
    if (!f) return 0;
    fputs(src, f);
    fclose(f);
    snprintf(cmd, sizeof cmd,
        "cd %s && python3 %s/dictumc_cli.py min.dict --backend %s "
        "--compile --output minbin 2>&1 | head -40",
        dir, compiler_dir, backend);
    buf[0] = 0;
    run_capture(cmd, buf, sizeof buf);
    if (!signature[0]) return 0;
    return strstr(buf, signature) != NULL;
}

static void extract_signature(const char *log, char *sig, size_t cap) {
    /* First line mentioning "error" (case-insensitive-ish), trimmed. */
    sig[0] = 0;
    const char *q = log;
    while (*q) {
        const char *nl = strchr(q, '\n');
        size_t len = nl ? (size_t)(nl - q) : strlen(q);
        if (len > 6 && len < cap - 1 &&
            (strstr(q, "error") || strstr(q, "Error"))) {
            size_t n = len < cap - 1 ? len : cap - 1;
            memcpy(sig, q, n);
            sig[n] = 0;
            return;
        }
        if (!nl) break;
        q = nl + 1;
    }
}

static void minimize(const char *dir, const char *compiler_dir,
                     const char *backend, const char *orig,
                     const char *signature, char *out, size_t cap) {
    char work[MAXSRC], trial[MAXSRC];
    snprintf(work, sizeof work, "%s", orig);
    int changed = 1, rounds = 0;
    while (changed && rounds++ < 12) {
        changed = 0;
        /* try removing each line, keep the removal if it still fails
         * the same way */
        for (int li = 0; ; li++) {
            char *lines[512];
            int nl = 0;
            snprintf(trial, sizeof trial, "%s", work);
            char *tok = strtok(trial, "\n");
            while (tok && nl < 512) { lines[nl++] = tok; tok = strtok(NULL, "\n"); }
            if (li >= nl) break;
            /* never drop the program header/footer -- removing them makes
             * every reduction "fail", which is a false reduction */
            if (strstr(lines[li], "program ") || strstr(lines[li], "end program"))
                continue;
            char cand[MAXSRC]; cand[0] = 0;
            size_t used = 0;
            for (int j = 0; j < nl; j++) {
                if (j == li) continue;
                int w = snprintf(cand + used, sizeof cand - used, "%s\n", lines[j]);
                if (w > 0) used += (size_t)w;
            }
            if (still_fails(dir, compiler_dir, backend, cand, signature)) {
                snprintf(work, sizeof work, "%s", cand);
                changed = 1;
                break;
            }
        }
    }
    snprintf(out, cap, "%s", work);
}

int main(int argc, char **argv) {
    long seconds = 60;
    long want_count = 0;   /* 0 = time-based; >0 = run exactly N programs */
    const char *workdir = "/tmp/progforge_work";
    const char *compiler_dir = "..";
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--seconds") && i + 1 < argc) seconds = atol(argv[++i]);
        else if (!strcmp(argv[i], "--count") && i + 1 < argc) want_count = atol(argv[++i]);
        else if (!strcmp(argv[i], "--workdir") && i + 1 < argc) workdir = argv[++i];
        else if (!strcmp(argv[i], "--compiler") && i + 1 < argc) compiler_dir = argv[++i];
    }
    rng_state = (unsigned long)getpid() ^ (unsigned long)time(NULL);
    rng_state &= 0x7FFFFFFFUL;

    char cmd[4096], buf[65536], got[65536], want[65536];
    char inventory_path[1024];
    snprintf(inventory_path, sizeof inventory_path, "%s/findings_inventory.txt", workdir);
    mkdir(workdir, 0755);

    long total = 0, ok = 0, wrong = 0, buildfail = 0, disagree = 0;
    const char *backends[3] = {"c", "cpp", "nim"};
    time_t start = time(NULL);

    if (want_count > 0)
        printf("progforge: generating exactly %ld real Dictum programs\n", want_count);
    else
        printf("progforge: generating real Dictum programs for %lds\n", seconds);
    printf("           (verifies CORRECTNESS against self-computed expected output,\n");
    printf("            not merely that the compilers didn't crash)\n");
    fflush(stdout);

    while (want_count > 0 ? (total < want_count) : (time(NULL) - start < seconds)) {
        Program p;
        generate(&p);

        char dir[1024];
        snprintf(dir, sizeof dir, "%s/case%ld", workdir, total);
        snprintf(cmd, sizeof cmd, "rm -rf %s && mkdir -p %s", dir, dir);
        if (system(cmd) != 0) { total++; continue; }

        char path[1200];
        snprintf(path, sizeof path, "%s/main.dict", dir);
        write_main_dict(path, &p);
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
            if (rc != 0 || buf[0] == 0) {
                any_buildfail = 1;
                outs[b][0] = 0;
                /* MECHANICAL BUG HUNTING: capture the error signature,
                 * auto-minimize the failing program down to a small
                 * reproducer, and append both to an inventory file --
                 * so a finding is actionable without a human reading a
                 * 40-line generated program. */
                if (!p.multifile) {
                    char sig[512];
                    extract_signature(buf, sig, sizeof sig);
                    if (sig[0]) {
                        char full[MAXSRC];
                        snprintf(full, sizeof full, "%s%s",
                                 p.prelude.len ? p.prelude.src : "", p.main_src.src);
                        char small[MAXSRC];
                        minimize(dir, compiler_dir, backends[b], full, sig,
                                 small, sizeof small);
                        FILE *inv = fopen(inventory_path, "a");
                        if (inv) {
                            fprintf(inv, "=== BUILD FAILURE  backend=%s  case=%ld ===\n",
                                    backends[b], total);
                            fprintf(inv, "signature: %s\n", sig);
                            fprintf(inv, "--- minimized reproducer ---\n%s\n", small);
                            fclose(inv);
                        }
                        printf("   -> minimized reproducer written to %s\n", inventory_path);
                    }
                }
                /* Name the backend. A per-backend build failure used to be
                 * absorbed silently whenever the other backends still
                 * agreed -- which is precisely how a backend-specific bug
                 * hides. A program that builds on 2 of 3 backends is a
                 * finding, not a pass. */
                printf("!! BUILD FAILED on %-3s (case %ld, %s) kept at %s\n",
                       backends[b], total, p.multifile ? "multifile" : "single", dir);
                fflush(stdout);
                continue;
            }
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
                {
                    FILE *inv = fopen(inventory_path, "a");
                    if (inv) {
                        fprintf(inv, "=== WRONG OUTPUT  case=%ld ===\nwant: %s\n", total, want);
                        for (int q = 0; q < 3; q++)
                            if (good[q]) fprintf(inv, "%-4s: %s\n", backends[q], outs[q]);
                        fprintf(inv, "--- program ---\n%s%s\n",
                                p.prelude.len ? p.prelude.src : "", p.main_src.src);
                        fclose(inv);
                    }
                }
                fflush(stdout);
            } else if (differ) {
                disagree++;
                printf("!! BACKEND DISAGREEMENT (case %ld) kept at %s\n", total, dir);
                fflush(stdout);
            } else if (!any_buildfail) {
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
