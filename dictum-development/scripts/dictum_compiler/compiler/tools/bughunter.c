#define _DEFAULT_SOURCE
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <math.h>
#include <setjmp.h>
#include "dictum_core.h"
#include "dictum_error.h"

typedef const char* dictum_text;

#include "dictum_text.h"
#include "dictum_file.h"

/* ── Dictum stdlib ── */
#include "dictum_file.h"
#include "dictum_text.h"

extern int32_t system(dictum_text);
static inline int32_t run_shell(dictum_text a0) { return system(a0); }
extern int32_t getpid(void);
extern int32_t dictum_flush_stdout(void);
static inline int32_t flush_stdout(void) { return dictum_flush_stdout(); }
int32_t test_one_backend(dictum_text mutant, dictum_text backend);
bool smoke_test_backend(dictum_text backend);

int32_t test_one_backend(dictum_text mutant, dictum_text backend) {
    /* @dictum-line:10 */
    #line 10 "<dict-source>"
    bool wrote = 0;
    /* @dictum-line:11 */
    #line 11 "<dict-source>"
    wrote = dictum_file_write("/tmp/bughunt_candidate.dict", mutant);
    /* @dictum-line:13 */
    #line 13 "<dict-source>"
    dictum_text cmd_a = "";
    /* @dictum-line:14 */
    #line 14 "<dict-source>"
    cmd_a = dictum_text_concat("cd .. && timeout 10 python3 dictumc_cli.py /tmp/bughunt_candidate.dict --backend ", backend);
    /* @dictum-line:15 */
    #line 15 "<dict-source>"
    dictum_text cmd_b = "";
    /* @dictum-line:16 */
    #line 16 "<dict-source>"
    cmd_b = dictum_text_concat(cmd_a, " --compile --output /tmp/bughunt_out_");
    /* @dictum-line:17 */
    #line 17 "<dict-source>"
    dictum_text cmd_c = "";
    /* @dictum-line:18 */
    #line 18 "<dict-source>"
    cmd_c = dictum_text_concat(cmd_b, backend);
    /* @dictum-line:19 */
    #line 19 "<dict-source>"
    dictum_text cmd = "";
    /* @dictum-line:20 */
    #line 20 "<dict-source>"
    cmd = dictum_text_concat(cmd_c, " > /tmp/bughunt_log.txt 2>&1; date +%s > /tmp/bughunt_now.txt");
    /* @dictum-line:22 */
    #line 22 "<dict-source>"
    int32_t status = 0;
    /* @dictum-line:23 */
    #line 23 "<dict-source>"
    status = run_shell(cmd);
    /* @dictum-line:25 */
    #line 25 "<dict-source>"
    dictum_text log = "";
    /* @dictum-line:26 */
    #line 26 "<dict-source>"
    log = dictum_file_read("/tmp/bughunt_log.txt");
    /* @dictum-line:28 */
    #line 28 "<dict-source>"
    bool has_traceback = 0;
    /* @dictum-line:29 */
    #line 29 "<dict-source>"
    has_traceback = dictum_text_contains(log, "Traceback");
    /* @dictum-line:30 */
    #line 30 "<dict-source>"
    if ((has_traceback == 1)) {
        /* @dictum-line:31 */
        #line 31 "<dict-source>"
        return 3;
    }
    /* @dictum-line:34 */
    #line 34 "<dict-source>"
    bool has_internal_error = 0;
    /* @dictum-line:35 */
    #line 35 "<dict-source>"
    has_internal_error = dictum_text_contains(log, "dictumc: internal error");
    /* @dictum-line:36 */
    #line 36 "<dict-source>"
    if ((has_internal_error == 1)) {
        /* @dictum-line:37 */
        #line 37 "<dict-source>"
        return 2;
    }
    /* @dictum-line:40 */
    #line 40 "<dict-source>"
    bool has_dictumc_msg = 0;
    /* @dictum-line:41 */
    #line 41 "<dict-source>"
    has_dictumc_msg = dictum_text_contains(log, " error");
    /* @dictum-line:42 */
    #line 42 "<dict-source>"
    if ((has_dictumc_msg == 1)) {
        /* @dictum-line:43 */
        #line 43 "<dict-source>"
        return 1;
    }
    /* @dictum-line:46 */
    #line 46 "<dict-source>"
    bool has_launcher_fail = 0;
    /* @dictum-line:47 */
    #line 47 "<dict-source>"
    has_launcher_fail = dictum_text_contains(log, "No such file");
    /* @dictum-line:48 */
    #line 48 "<dict-source>"
    if ((has_launcher_fail == 1)) {
        /* @dictum-line:49 */
        #line 49 "<dict-source>"
        return 4;
    }
    /* @dictum-line:52 */
    #line 52 "<dict-source>"
    if ((status == 0)) {
        /* @dictum-line:53 */
        #line 53 "<dict-source>"
        return 0;
    }
    /* @dictum-line:55 */
    #line 55 "<dict-source>"
    return 1;
}

bool smoke_test_backend(dictum_text backend) {
    /* @dictum-line:60 */
    #line 60 "<dict-source>"
    dictum_text smoke_src = "program smoke_test\n    print the text \"SMOKE_OK\"\nend program\n";
    /* @dictum-line:61 */
    #line 61 "<dict-source>"
    bool wrote = 0;
    /* @dictum-line:62 */
    #line 62 "<dict-source>"
    wrote = dictum_file_write("/tmp/bughunt_smoke.dict", smoke_src);
    /* @dictum-line:64 */
    #line 64 "<dict-source>"
    dictum_text sc_a = "";
    /* @dictum-line:65 */
    #line 65 "<dict-source>"
    sc_a = dictum_text_concat("cd .. && timeout 60 python3 dictumc_cli.py /tmp/bughunt_smoke.dict --backend ", backend);
    /* @dictum-line:66 */
    #line 66 "<dict-source>"
    dictum_text sc_b = "";
    /* @dictum-line:67 */
    #line 67 "<dict-source>"
    sc_b = dictum_text_concat(sc_a, " --compile --output /tmp/bughunt_smoke_out_");
    /* @dictum-line:68 */
    #line 68 "<dict-source>"
    dictum_text sc_c = "";
    /* @dictum-line:69 */
    #line 69 "<dict-source>"
    sc_c = dictum_text_concat(sc_b, backend);
    /* @dictum-line:70 */
    #line 70 "<dict-source>"
    dictum_text smoke_cmd = "";
    /* @dictum-line:71 */
    #line 71 "<dict-source>"
    smoke_cmd = dictum_text_concat(sc_c, " > /tmp/bughunt_smoke_log.txt 2>&1");
    /* @dictum-line:73 */
    #line 73 "<dict-source>"
    int32_t smoke_status = 0;
    /* @dictum-line:74 */
    #line 74 "<dict-source>"
    smoke_status = run_shell(smoke_cmd);
    /* @dictum-line:76 */
    #line 76 "<dict-source>"
    if ((smoke_status != 0)) {
        /* @dictum-line:77 */
        #line 77 "<dict-source>"
        return 0;
    }
    /* @dictum-line:80 */
    #line 80 "<dict-source>"
    dictum_text rc_a = "";
    /* @dictum-line:81 */
    #line 81 "<dict-source>"
    rc_a = dictum_text_concat("timeout 10 /tmp/bughunt_smoke_out_", backend);
    /* @dictum-line:82 */
    #line 82 "<dict-source>"
    dictum_text run_cmd = "";
    /* @dictum-line:83 */
    #line 83 "<dict-source>"
    run_cmd = dictum_text_concat(rc_a, " > /tmp/bughunt_smoke_run.txt 2>&1");
    /* @dictum-line:85 */
    #line 85 "<dict-source>"
    int32_t run_status = 0;
    /* @dictum-line:86 */
    #line 86 "<dict-source>"
    run_status = run_shell(run_cmd);
    /* @dictum-line:88 */
    #line 88 "<dict-source>"
    dictum_text run_out = "";
    /* @dictum-line:89 */
    #line 89 "<dict-source>"
    run_out = dictum_file_read("/tmp/bughunt_smoke_run.txt");
    /* @dictum-line:91 */
    #line 91 "<dict-source>"
    bool has_ok = 0;
    /* @dictum-line:92 */
    #line 92 "<dict-source>"
    has_ok = dictum_text_contains(run_out, "SMOKE_OK");
    /* @dictum-line:93 */
    #line 93 "<dict-source>"
    return has_ok;
}


dictum_text seed0 = "program s0\n    keep x as whole number with value 3\n    put x plus 4 into x\n    print the text \"x:\" and x\nend program\n";
dictum_text seed1 = "program s1\n    keep xs as growable list of whole number with no value\n    add 1 to xs\n    add 2 to xs\n    print the text \"count:\" and the count of xs\nend program\n";
dictum_text seed2 = "program s2\n    keep a as whole number with value 9\n    keep b as whole number with value 2\n    if a is greater than b then\n        print the text \"yes\"\n    otherwise\n        print the text \"no\"\n    end if\nend program\n";
dictum_text duration_str = "60";
bool have_config = 0;
int32_t duration_seconds = 60;
bool enabled_c = 0;
bool enabled_cpp = 0;
bool enabled_nim = 0;
int32_t smoke_flush_r = 0;
int32_t pid = 0;
int32_t rng_state = 0;
dictum_text start_str = "0";
int32_t s1 = 0;
int32_t start_time = 0;
int32_t total_runs = 0;
int32_t crashes_c = 0;
int32_t crashes_cpp = 0;
int32_t crashes_nim = 0;
int32_t internal_c = 0;
int32_t internal_cpp = 0;
int32_t internal_nim = 0;
int32_t rejects_c = 0;
int32_t rejects_cpp = 0;
int32_t rejects_nim = 0;
int32_t ok_c = 0;
int32_t ok_cpp = 0;
int32_t ok_nim = 0;
int32_t setup_fail_c = 0;
int32_t setup_fail_cpp = 0;
int32_t setup_fail_nim = 0;
int32_t findings_count = 0;
int32_t skipped_c = 0;
int32_t skipped_cpp = 0;
int32_t skipped_nim = 0;
int32_t elapsed = 0;
bool keep_going = 1;
int32_t last_heartbeat = 0;
int32_t final_flush_r = 0;



int main(void) {
    /* @dictum-line:104 */
    #line 104 "<dict-source>"
    have_config = dictum_file_exists("/tmp/bughunt_duration_seconds.txt");
    /* @dictum-line:105 */
    #line 105 "<dict-source>"
    if ((have_config == 1)) {
        /* @dictum-line:106 */
        #line 106 "<dict-source>"
        duration_str = dictum_file_read("/tmp/bughunt_duration_seconds.txt");
    }
    /* @dictum-line:109 */
    #line 109 "<dict-source>"
    duration_seconds = dictum_text_to_int(duration_str);
    /* @dictum-line:112 */
    #line 112 "<dict-source>"
    enabled_c = smoke_test_backend("c");
    /* @dictum-line:114 */
    #line 114 "<dict-source>"
    enabled_cpp = smoke_test_backend("cpp");
    /* @dictum-line:116 */
    #line 116 "<dict-source>"
    enabled_nim = smoke_test_backend("nim");
    /* @dictum-line:117 */
    #line 117 "<dict-source>"
    printf("SMOKE TEST -- c:%dcpp:%dnim:%d", enabled_c, enabled_cpp, enabled_nim);
    /* @dictum-line:118 */
    #line 118 "<dict-source>"
    printf("(1 = compiles AND runs correctly, 0 = disabled for this run, e.g. toolchain missing)");
    /* @dictum-line:120 */
    #line 120 "<dict-source>"
    smoke_flush_r = flush_stdout();
    /* @dictum-line:123 */
    #line 123 "<dict-source>"
    pid = getpid();
    /* @dictum-line:125 */
    #line 125 "<dict-source>"
    rng_state = (pid + 12345);
    /* @dictum-line:129 */
    #line 129 "<dict-source>"
    s1 = run_shell("date +%s > /tmp/bughunt_start.txt");
    /* @dictum-line:130 */
    #line 130 "<dict-source>"
    start_str = dictum_file_read("/tmp/bughunt_start.txt");
    /* @dictum-line:132 */
    #line 132 "<dict-source>"
    start_time = dictum_text_to_int(start_str);
    /* @dictum-line:159 */
    #line 159 "<dict-source>"
    while ((keep_going == 1)) {
        /* @dictum-line:161 */
        #line 161 "<dict-source>"
        rng_state = (rng_state * 75);
        /* @dictum-line:162 */
        #line 162 "<dict-source>"
        rng_state = (rng_state + 74);
        /* @dictum-line:163 */
        #line 163 "<dict-source>"
        rng_state = (rng_state % 65537);
        /* @dictum-line:164 */
        #line 164 "<dict-source>"
        int32_t seed_pick = 0;
        /* @dictum-line:165 */
        #line 165 "<dict-source>"
        seed_pick = (rng_state % 3);
        /* @dictum-line:167 */
        #line 167 "<dict-source>"
        dictum_text base = "";
        /* @dictum-line:168 */
        #line 168 "<dict-source>"
        if ((seed_pick == 0)) {
            /* @dictum-line:169 */
            #line 169 "<dict-source>"
            base = seed0;
        }
        /* @dictum-line:171 */
        #line 171 "<dict-source>"
        if ((seed_pick == 1)) {
            /* @dictum-line:172 */
            #line 172 "<dict-source>"
            base = seed1;
        }
        /* @dictum-line:174 */
        #line 174 "<dict-source>"
        if ((seed_pick == 2)) {
            /* @dictum-line:175 */
            #line 175 "<dict-source>"
            base = seed2;
        }
        /* @dictum-line:178 */
        #line 178 "<dict-source>"
        rng_state = (rng_state * 75);
        /* @dictum-line:179 */
        #line 179 "<dict-source>"
        rng_state = (rng_state + 74);
        /* @dictum-line:180 */
        #line 180 "<dict-source>"
        rng_state = (rng_state % 65537);
        /* @dictum-line:181 */
        #line 181 "<dict-source>"
        int32_t mutation_pick = 0;
        /* @dictum-line:182 */
        #line 182 "<dict-source>"
        mutation_pick = (rng_state % 2);
        /* @dictum-line:184 */
        #line 184 "<dict-source>"
        dictum_text mutant = "";
        /* @dictum-line:185 */
        #line 185 "<dict-source>"
        if ((mutation_pick == 0)) {
            /* @dictum-line:186 */
            #line 186 "<dict-source>"
            mutant = dictum_text_replace(base, "plus", "modulo");
        }
        /* @dictum-line:188 */
        #line 188 "<dict-source>"
        if ((mutation_pick == 1)) {
            /* @dictum-line:189 */
            #line 189 "<dict-source>"
            int32_t base_len = 0;
            /* @dictum-line:190 */
            #line 190 "<dict-source>"
            base_len = dictum_text_length(base);
            /* @dictum-line:191 */
            #line 191 "<dict-source>"
            int32_t cut_point = 0;
            /* @dictum-line:192 */
            #line 192 "<dict-source>"
            cut_point = (rng_state % base_len);
            /* @dictum-line:193 */
            #line 193 "<dict-source>"
            mutant = dictum_text_slice(base, 0, cut_point);
        }
        /* @dictum-line:196 */
        #line 196 "<dict-source>"
        if ((enabled_c == 1)) {
            /* @dictum-line:197 */
            #line 197 "<dict-source>"
            int32_t result_c = 0;
            /* @dictum-line:198 */
            #line 198 "<dict-source>"
            result_c = test_one_backend(mutant, "c");
            /* @dictum-line:199 */
            #line 199 "<dict-source>"
            if ((result_c == 3)) {
                /* @dictum-line:200 */
                #line 200 "<dict-source>"
                crashes_c = (crashes_c + 1);
            }
            /* @dictum-line:202 */
            #line 202 "<dict-source>"
            if ((result_c == 2)) {
                /* @dictum-line:203 */
                #line 203 "<dict-source>"
                internal_c = (internal_c + 1);
            }
            /* @dictum-line:205 */
            #line 205 "<dict-source>"
            if ((result_c == 1)) {
                /* @dictum-line:206 */
                #line 206 "<dict-source>"
                rejects_c = (rejects_c + 1);
            }
            /* @dictum-line:208 */
            #line 208 "<dict-source>"
            if ((result_c == 0)) {
                /* @dictum-line:209 */
                #line 209 "<dict-source>"
                ok_c = (ok_c + 1);
            }
            /* @dictum-line:211 */
            #line 211 "<dict-source>"
            if ((result_c == 4)) {
                /* @dictum-line:212 */
                #line 212 "<dict-source>"
                setup_fail_c = (setup_fail_c + 1);
            }
            /* @dictum-line:214 */
            #line 214 "<dict-source>"
            if ((result_c == 2)) {
                /* @dictum-line:215 */
                #line 215 "<dict-source>"
                findings_count = (findings_count + 1);
                /* @dictum-line:216 */
                #line 216 "<dict-source>"
                dictum_text fname_a = "";
                /* @dictum-line:217 */
                #line 217 "<dict-source>"
                fname_a = dictum_text_concat("findings/case_", "c_");
                /* @dictum-line:218 */
                #line 218 "<dict-source>"
                dictum_text fcount_str = "";
                /* @dictum-line:219 */
                #line 219 "<dict-source>"
                fcount_str = dictum_text_from_int(findings_count);
                /* @dictum-line:220 */
                #line 220 "<dict-source>"
                dictum_text fname_b = "";
                /* @dictum-line:221 */
                #line 221 "<dict-source>"
                fname_b = dictum_text_concat(fname_a, fcount_str);
                /* @dictum-line:222 */
                #line 222 "<dict-source>"
                dictum_text fname = "";
                /* @dictum-line:223 */
                #line 223 "<dict-source>"
                fname = dictum_text_concat(fname_b, ".dict");
                /* @dictum-line:224 */
                #line 224 "<dict-source>"
                bool w1 = 0;
                /* @dictum-line:225 */
                #line 225 "<dict-source>"
                w1 = dictum_file_write(fname, mutant);
            }
            /* @dictum-line:227 */
            #line 227 "<dict-source>"
            if ((result_c == 3)) {
                /* @dictum-line:228 */
                #line 228 "<dict-source>"
                findings_count = (findings_count + 1);
                /* @dictum-line:229 */
                #line 229 "<dict-source>"
                dictum_text fname_a_x = "";
                /* @dictum-line:230 */
                #line 230 "<dict-source>"
                fname_a_x = dictum_text_concat("findings/case_", "c_");
                /* @dictum-line:231 */
                #line 231 "<dict-source>"
                dictum_text fcount_str_x = "";
                /* @dictum-line:232 */
                #line 232 "<dict-source>"
                fcount_str_x = dictum_text_from_int(findings_count);
                /* @dictum-line:233 */
                #line 233 "<dict-source>"
                dictum_text fname_b_x = "";
                /* @dictum-line:234 */
                #line 234 "<dict-source>"
                fname_b_x = dictum_text_concat(fname_a_x, fcount_str_x);
                /* @dictum-line:235 */
                #line 235 "<dict-source>"
                dictum_text fname_x = "";
                /* @dictum-line:236 */
                #line 236 "<dict-source>"
                fname_x = dictum_text_concat(fname_b_x, ".dict");
                /* @dictum-line:237 */
                #line 237 "<dict-source>"
                bool w1_x = 0;
                /* @dictum-line:238 */
                #line 238 "<dict-source>"
                w1_x = dictum_file_write(fname_x, mutant);
            }
        } else {
            /* @dictum-line:241 */
            #line 241 "<dict-source>"
            skipped_c = (skipped_c + 1);
        }
        /* @dictum-line:244 */
        #line 244 "<dict-source>"
        if ((enabled_cpp == 1)) {
            /* @dictum-line:245 */
            #line 245 "<dict-source>"
            int32_t result_cpp = 0;
            /* @dictum-line:246 */
            #line 246 "<dict-source>"
            result_cpp = test_one_backend(mutant, "cpp");
            /* @dictum-line:247 */
            #line 247 "<dict-source>"
            if ((result_cpp == 3)) {
                /* @dictum-line:248 */
                #line 248 "<dict-source>"
                crashes_cpp = (crashes_cpp + 1);
            }
            /* @dictum-line:250 */
            #line 250 "<dict-source>"
            if ((result_cpp == 2)) {
                /* @dictum-line:251 */
                #line 251 "<dict-source>"
                internal_cpp = (internal_cpp + 1);
            }
            /* @dictum-line:253 */
            #line 253 "<dict-source>"
            if ((result_cpp == 1)) {
                /* @dictum-line:254 */
                #line 254 "<dict-source>"
                rejects_cpp = (rejects_cpp + 1);
            }
            /* @dictum-line:256 */
            #line 256 "<dict-source>"
            if ((result_cpp == 0)) {
                /* @dictum-line:257 */
                #line 257 "<dict-source>"
                ok_cpp = (ok_cpp + 1);
            }
            /* @dictum-line:259 */
            #line 259 "<dict-source>"
            if ((result_cpp == 4)) {
                /* @dictum-line:260 */
                #line 260 "<dict-source>"
                setup_fail_cpp = (setup_fail_cpp + 1);
            }
            /* @dictum-line:262 */
            #line 262 "<dict-source>"
            if ((result_cpp == 2)) {
                /* @dictum-line:263 */
                #line 263 "<dict-source>"
                findings_count = (findings_count + 1);
                /* @dictum-line:264 */
                #line 264 "<dict-source>"
                dictum_text fname_a2 = "";
                /* @dictum-line:265 */
                #line 265 "<dict-source>"
                fname_a2 = dictum_text_concat("findings/case_", "cpp_");
                /* @dictum-line:266 */
                #line 266 "<dict-source>"
                dictum_text fcount_str2 = "";
                /* @dictum-line:267 */
                #line 267 "<dict-source>"
                fcount_str2 = dictum_text_from_int(findings_count);
                /* @dictum-line:268 */
                #line 268 "<dict-source>"
                dictum_text fname_b2 = "";
                /* @dictum-line:269 */
                #line 269 "<dict-source>"
                fname_b2 = dictum_text_concat(fname_a2, fcount_str2);
                /* @dictum-line:270 */
                #line 270 "<dict-source>"
                dictum_text fname2 = "";
                /* @dictum-line:271 */
                #line 271 "<dict-source>"
                fname2 = dictum_text_concat(fname_b2, ".dict");
                /* @dictum-line:272 */
                #line 272 "<dict-source>"
                bool w2 = 0;
                /* @dictum-line:273 */
                #line 273 "<dict-source>"
                w2 = dictum_file_write(fname2, mutant);
            }
            /* @dictum-line:275 */
            #line 275 "<dict-source>"
            if ((result_cpp == 3)) {
                /* @dictum-line:276 */
                #line 276 "<dict-source>"
                findings_count = (findings_count + 1);
                /* @dictum-line:277 */
                #line 277 "<dict-source>"
                dictum_text fname_a2_x = "";
                /* @dictum-line:278 */
                #line 278 "<dict-source>"
                fname_a2_x = dictum_text_concat("findings/case_", "cpp_");
                /* @dictum-line:279 */
                #line 279 "<dict-source>"
                dictum_text fcount_str2_x = "";
                /* @dictum-line:280 */
                #line 280 "<dict-source>"
                fcount_str2_x = dictum_text_from_int(findings_count);
                /* @dictum-line:281 */
                #line 281 "<dict-source>"
                dictum_text fname_b2_x = "";
                /* @dictum-line:282 */
                #line 282 "<dict-source>"
                fname_b2_x = dictum_text_concat(fname_a2_x, fcount_str2_x);
                /* @dictum-line:283 */
                #line 283 "<dict-source>"
                dictum_text fname2_x = "";
                /* @dictum-line:284 */
                #line 284 "<dict-source>"
                fname2_x = dictum_text_concat(fname_b2_x, ".dict");
                /* @dictum-line:285 */
                #line 285 "<dict-source>"
                bool w2_x = 0;
                /* @dictum-line:286 */
                #line 286 "<dict-source>"
                w2_x = dictum_file_write(fname2_x, mutant);
            }
        } else {
            /* @dictum-line:289 */
            #line 289 "<dict-source>"
            skipped_cpp = (skipped_cpp + 1);
        }
        /* @dictum-line:292 */
        #line 292 "<dict-source>"
        if ((enabled_nim == 1)) {
            /* @dictum-line:293 */
            #line 293 "<dict-source>"
            int32_t result_nim = 0;
            /* @dictum-line:294 */
            #line 294 "<dict-source>"
            result_nim = test_one_backend(mutant, "nim");
            /* @dictum-line:295 */
            #line 295 "<dict-source>"
            if ((result_nim == 3)) {
                /* @dictum-line:296 */
                #line 296 "<dict-source>"
                crashes_nim = (crashes_nim + 1);
            }
            /* @dictum-line:298 */
            #line 298 "<dict-source>"
            if ((result_nim == 2)) {
                /* @dictum-line:299 */
                #line 299 "<dict-source>"
                internal_nim = (internal_nim + 1);
            }
            /* @dictum-line:301 */
            #line 301 "<dict-source>"
            if ((result_nim == 1)) {
                /* @dictum-line:302 */
                #line 302 "<dict-source>"
                rejects_nim = (rejects_nim + 1);
            }
            /* @dictum-line:304 */
            #line 304 "<dict-source>"
            if ((result_nim == 0)) {
                /* @dictum-line:305 */
                #line 305 "<dict-source>"
                ok_nim = (ok_nim + 1);
            }
            /* @dictum-line:307 */
            #line 307 "<dict-source>"
            if ((result_nim == 4)) {
                /* @dictum-line:308 */
                #line 308 "<dict-source>"
                setup_fail_nim = (setup_fail_nim + 1);
            }
            /* @dictum-line:310 */
            #line 310 "<dict-source>"
            if ((result_nim == 2)) {
                /* @dictum-line:311 */
                #line 311 "<dict-source>"
                findings_count = (findings_count + 1);
                /* @dictum-line:312 */
                #line 312 "<dict-source>"
                dictum_text fname_a3 = "";
                /* @dictum-line:313 */
                #line 313 "<dict-source>"
                fname_a3 = dictum_text_concat("findings/case_", "nim_");
                /* @dictum-line:314 */
                #line 314 "<dict-source>"
                dictum_text fcount_str3 = "";
                /* @dictum-line:315 */
                #line 315 "<dict-source>"
                fcount_str3 = dictum_text_from_int(findings_count);
                /* @dictum-line:316 */
                #line 316 "<dict-source>"
                dictum_text fname_b3 = "";
                /* @dictum-line:317 */
                #line 317 "<dict-source>"
                fname_b3 = dictum_text_concat(fname_a3, fcount_str3);
                /* @dictum-line:318 */
                #line 318 "<dict-source>"
                dictum_text fname3 = "";
                /* @dictum-line:319 */
                #line 319 "<dict-source>"
                fname3 = dictum_text_concat(fname_b3, ".dict");
                /* @dictum-line:320 */
                #line 320 "<dict-source>"
                bool w3 = 0;
                /* @dictum-line:321 */
                #line 321 "<dict-source>"
                w3 = dictum_file_write(fname3, mutant);
            }
            /* @dictum-line:323 */
            #line 323 "<dict-source>"
            if ((result_nim == 3)) {
                /* @dictum-line:324 */
                #line 324 "<dict-source>"
                findings_count = (findings_count + 1);
                /* @dictum-line:325 */
                #line 325 "<dict-source>"
                dictum_text fname_a3_x = "";
                /* @dictum-line:326 */
                #line 326 "<dict-source>"
                fname_a3_x = dictum_text_concat("findings/case_", "nim_");
                /* @dictum-line:327 */
                #line 327 "<dict-source>"
                dictum_text fcount_str3_x = "";
                /* @dictum-line:328 */
                #line 328 "<dict-source>"
                fcount_str3_x = dictum_text_from_int(findings_count);
                /* @dictum-line:329 */
                #line 329 "<dict-source>"
                dictum_text fname_b3_x = "";
                /* @dictum-line:330 */
                #line 330 "<dict-source>"
                fname_b3_x = dictum_text_concat(fname_a3_x, fcount_str3_x);
                /* @dictum-line:331 */
                #line 331 "<dict-source>"
                dictum_text fname3_x = "";
                /* @dictum-line:332 */
                #line 332 "<dict-source>"
                fname3_x = dictum_text_concat(fname_b3_x, ".dict");
                /* @dictum-line:333 */
                #line 333 "<dict-source>"
                bool w3_x = 0;
                /* @dictum-line:334 */
                #line 334 "<dict-source>"
                w3_x = dictum_file_write(fname3_x, mutant);
            }
        } else {
            /* @dictum-line:337 */
            #line 337 "<dict-source>"
            skipped_nim = (skipped_nim + 1);
        }
        /* @dictum-line:340 */
        #line 340 "<dict-source>"
        total_runs = (total_runs + 1);
        /* @dictum-line:342 */
        #line 342 "<dict-source>"
        dictum_text now_str = "0";
        /* @dictum-line:343 */
        #line 343 "<dict-source>"
        now_str = dictum_file_read("/tmp/bughunt_now.txt");
        /* @dictum-line:344 */
        #line 344 "<dict-source>"
        int32_t now_time = 0;
        /* @dictum-line:345 */
        #line 345 "<dict-source>"
        now_time = dictum_text_to_int(now_str);
        /* @dictum-line:346 */
        #line 346 "<dict-source>"
        elapsed = (now_time - start_time);
        /* @dictum-line:348 */
        #line 348 "<dict-source>"
        dictum_text summary = "";
        /* @dictum-line:349 */
        #line 349 "<dict-source>"
        summary = dictum_text_concat("elapsed_seconds:", "");
        /* @dictum-line:350 */
        #line 350 "<dict-source>"
        dictum_text es = "";
        /* @dictum-line:351 */
        #line 351 "<dict-source>"
        es = dictum_text_from_int(elapsed);
        /* @dictum-line:352 */
        #line 352 "<dict-source>"
        summary = dictum_text_concat(summary, es);
        /* @dictum-line:353 */
        #line 353 "<dict-source>"
        summary = dictum_text_concat(summary, "\ntotal_runs:");
        /* @dictum-line:354 */
        #line 354 "<dict-source>"
        dictum_text ts = "";
        /* @dictum-line:355 */
        #line 355 "<dict-source>"
        ts = dictum_text_from_int(total_runs);
        /* @dictum-line:356 */
        #line 356 "<dict-source>"
        summary = dictum_text_concat(summary, ts);
        /* @dictum-line:357 */
        #line 357 "<dict-source>"
        summary = dictum_text_concat(summary, "\nfindings_count:");
        /* @dictum-line:358 */
        #line 358 "<dict-source>"
        dictum_text fcs = "";
        /* @dictum-line:359 */
        #line 359 "<dict-source>"
        fcs = dictum_text_from_int(findings_count);
        /* @dictum-line:360 */
        #line 360 "<dict-source>"
        summary = dictum_text_concat(summary, fcs);
        /* @dictum-line:361 */
        #line 361 "<dict-source>"
        summary = dictum_text_concat(summary, "\nc: crashes=");
        /* @dictum-line:362 */
        #line 362 "<dict-source>"
        dictum_text cc = "";
        /* @dictum-line:363 */
        #line 363 "<dict-source>"
        cc = dictum_text_from_int(crashes_c);
        /* @dictum-line:364 */
        #line 364 "<dict-source>"
        summary = dictum_text_concat(summary, cc);
        /* @dictum-line:365 */
        #line 365 "<dict-source>"
        summary = dictum_text_concat(summary, " internal=");
        /* @dictum-line:366 */
        #line 366 "<dict-source>"
        dictum_text ic = "";
        /* @dictum-line:367 */
        #line 367 "<dict-source>"
        ic = dictum_text_from_int(internal_c);
        /* @dictum-line:368 */
        #line 368 "<dict-source>"
        summary = dictum_text_concat(summary, ic);
        /* @dictum-line:369 */
        #line 369 "<dict-source>"
        summary = dictum_text_concat(summary, " rejects=");
        /* @dictum-line:370 */
        #line 370 "<dict-source>"
        dictum_text rc = "";
        /* @dictum-line:371 */
        #line 371 "<dict-source>"
        rc = dictum_text_from_int(rejects_c);
        /* @dictum-line:372 */
        #line 372 "<dict-source>"
        summary = dictum_text_concat(summary, rc);
        /* @dictum-line:373 */
        #line 373 "<dict-source>"
        summary = dictum_text_concat(summary, " ok=");
        /* @dictum-line:374 */
        #line 374 "<dict-source>"
        dictum_text okc = "";
        /* @dictum-line:375 */
        #line 375 "<dict-source>"
        okc = dictum_text_from_int(ok_c);
        /* @dictum-line:376 */
        #line 376 "<dict-source>"
        summary = dictum_text_concat(summary, okc);
        /* @dictum-line:377 */
        #line 377 "<dict-source>"
        summary = dictum_text_concat(summary, "\ncpp: crashes=");
        /* @dictum-line:378 */
        #line 378 "<dict-source>"
        dictum_text ccpp = "";
        /* @dictum-line:379 */
        #line 379 "<dict-source>"
        ccpp = dictum_text_from_int(crashes_cpp);
        /* @dictum-line:380 */
        #line 380 "<dict-source>"
        summary = dictum_text_concat(summary, ccpp);
        /* @dictum-line:381 */
        #line 381 "<dict-source>"
        summary = dictum_text_concat(summary, " internal=");
        /* @dictum-line:382 */
        #line 382 "<dict-source>"
        dictum_text icpp = "";
        /* @dictum-line:383 */
        #line 383 "<dict-source>"
        icpp = dictum_text_from_int(internal_cpp);
        /* @dictum-line:384 */
        #line 384 "<dict-source>"
        summary = dictum_text_concat(summary, icpp);
        /* @dictum-line:385 */
        #line 385 "<dict-source>"
        summary = dictum_text_concat(summary, " rejects=");
        /* @dictum-line:386 */
        #line 386 "<dict-source>"
        dictum_text rcpp = "";
        /* @dictum-line:387 */
        #line 387 "<dict-source>"
        rcpp = dictum_text_from_int(rejects_cpp);
        /* @dictum-line:388 */
        #line 388 "<dict-source>"
        summary = dictum_text_concat(summary, rcpp);
        /* @dictum-line:389 */
        #line 389 "<dict-source>"
        summary = dictum_text_concat(summary, " ok=");
        /* @dictum-line:390 */
        #line 390 "<dict-source>"
        dictum_text okcpp = "";
        /* @dictum-line:391 */
        #line 391 "<dict-source>"
        okcpp = dictum_text_from_int(ok_cpp);
        /* @dictum-line:392 */
        #line 392 "<dict-source>"
        summary = dictum_text_concat(summary, okcpp);
        /* @dictum-line:393 */
        #line 393 "<dict-source>"
        summary = dictum_text_concat(summary, "\nnim: crashes=");
        /* @dictum-line:394 */
        #line 394 "<dict-source>"
        dictum_text cnim = "";
        /* @dictum-line:395 */
        #line 395 "<dict-source>"
        cnim = dictum_text_from_int(crashes_nim);
        /* @dictum-line:396 */
        #line 396 "<dict-source>"
        summary = dictum_text_concat(summary, cnim);
        /* @dictum-line:397 */
        #line 397 "<dict-source>"
        summary = dictum_text_concat(summary, " internal=");
        /* @dictum-line:398 */
        #line 398 "<dict-source>"
        dictum_text inim = "";
        /* @dictum-line:399 */
        #line 399 "<dict-source>"
        inim = dictum_text_from_int(internal_nim);
        /* @dictum-line:400 */
        #line 400 "<dict-source>"
        summary = dictum_text_concat(summary, inim);
        /* @dictum-line:401 */
        #line 401 "<dict-source>"
        summary = dictum_text_concat(summary, " rejects=");
        /* @dictum-line:402 */
        #line 402 "<dict-source>"
        dictum_text rnim = "";
        /* @dictum-line:403 */
        #line 403 "<dict-source>"
        rnim = dictum_text_from_int(rejects_nim);
        /* @dictum-line:404 */
        #line 404 "<dict-source>"
        summary = dictum_text_concat(summary, rnim);
        /* @dictum-line:405 */
        #line 405 "<dict-source>"
        summary = dictum_text_concat(summary, " ok=");
        /* @dictum-line:406 */
        #line 406 "<dict-source>"
        dictum_text oknim = "";
        /* @dictum-line:407 */
        #line 407 "<dict-source>"
        oknim = dictum_text_from_int(ok_nim);
        /* @dictum-line:408 */
        #line 408 "<dict-source>"
        summary = dictum_text_concat(summary, oknim);
        /* @dictum-line:409 */
        #line 409 "<dict-source>"
        summary = dictum_text_concat(summary, "\n");
        /* @dictum-line:410 */
        #line 410 "<dict-source>"
        bool w4 = 0;
        /* @dictum-line:411 */
        #line 411 "<dict-source>"
        w4 = dictum_file_write("summary.txt", summary);
        /* @dictum-line:413 */
        #line 413 "<dict-source>"
        int32_t since_heartbeat = 0;
        /* @dictum-line:414 */
        #line 414 "<dict-source>"
        since_heartbeat = (elapsed - last_heartbeat);
        /* @dictum-line:415 */
        #line 415 "<dict-source>"
        if ((since_heartbeat > 30)) {
            /* @dictum-line:416 */
            #line 416 "<dict-source>"
            printf("--- progress ---");
            /* @dictum-line:417 */
            #line 417 "<dict-source>"
            printf("%s", summary);
            /* @dictum-line:418 */
            #line 418 "<dict-source>"
            int32_t flush_r = 0;
            /* @dictum-line:419 */
            #line 419 "<dict-source>"
            flush_r = flush_stdout();
            /* @dictum-line:420 */
            #line 420 "<dict-source>"
            last_heartbeat = elapsed;
        }
        /* @dictum-line:423 */
        #line 423 "<dict-source>"
        if ((elapsed > duration_seconds)) {
            /* @dictum-line:424 */
            #line 424 "<dict-source>"
            keep_going = 0;
        }
        /* @dictum-line:426 */
        #line 426 "<dict-source>"
        if ((total_runs > 500000)) {
            /* @dictum-line:427 */
            #line 427 "<dict-source>"
            keep_going = 0;
        }
    }
    /* @dictum-line:431 */
    #line 431 "<dict-source>"
    printf("DONE. elapsed:%dtotal_runs:%d", elapsed, total_runs);
    /* @dictum-line:432 */
    #line 432 "<dict-source>"
    printf("findings_count:%d", findings_count);
    /* @dictum-line:434 */
    #line 434 "<dict-source>"
    final_flush_r = flush_stdout();
    return 0;
}