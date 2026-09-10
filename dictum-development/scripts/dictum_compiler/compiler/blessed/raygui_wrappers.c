/*
 * raygui_wrappers.c — blessed wrapper bridge for raygui's out-parameter
 * widgets, so they can be bound into Dictum via `import from C`.
 *
 * WHY THIS FILE EXISTS
 * ---------------------
 * raygui 5.x's interactive widgets report their state through a real C
 * out-parameter (`int *active`, `bool *checked`, `float *value`, ...).
 * Dictum's FFI has no address-of operator — `import from C` can bind a
 * function's signature, but Dictum can't take the address of one of its
 * own local variables to satisfy an `int*`/`bool*`/`float*` parameter.
 * See GUIDE_B_triage_protocol.md §2a ("a declared library isn't blessed
 * for the declared target" / bridge generation protocol) — this is the
 * exact, previously-identified fix pattern, generalized here into a
 * permanent, reusable asset instead of a one-off per-project wrapper.
 *
 * Each function below takes the CURRENT value in by value, copies it
 * into a real local variable, calls the actual raygui function with
 * `&local`, and returns the UPDATED value. This mirrors immediate-mode
 * GUI usage exactly: `x = dictum_raygui_toggle(bounds, "label", x)`.
 * The underlying raygui 5.x integer "result" code (click/press event)
 * is intentionally discarded — compare the returned value against what
 * you passed in if you need to know whether it changed this frame.
 *
 * BUILD
 * -----
 * Compile this file exactly once per project (it also carries the
 * RAYGUI_IMPLEMENTATION for raygui.h, which — like any single-header
 * library — must be defined in exactly one translation unit). Link the
 * resulting object alongside your Dictum-generated C/C++ output. Real
 * raylib (system-installed) is required; raygui.h itself is vendored
 * alongside this file under blessed/thirdparty/raygui.h so you don't
 * need to separately track it down.
 *
 *     gcc -c raygui_wrappers.c -I. -o raygui_wrappers.o
 *     gcc your_program.c raygui_wrappers.o -o your_program \
 *         -lraylib -lGL -lm -lpthread -ldl -lrt -lX11
 *
 * WHAT'S DELIBERATELY NOT HERE
 * -----------------------------
 * Widgets taking a mutable `char *` text buffer (GuiTextBox,
 * GuiValueBoxFloat, GuiMessageBox, GuiTextInputBox, GuiListView(Ex),
 * GuiTabBar(Ex)) are NOT wrapped here. Binding a mutable buffer as
 * Dictum `text` would be a second, more dangerous class of bug than
 * the out-param case: Dictum's `text` is not a fixed-size raw byte
 * buffer, and generate_import_c.py's type-mapper doesn't distinguish
 * `const char *` from `char *` (both currently map to `text`) — using
 * that mapping for a mutable buffer would compile clean and corrupt
 * memory at runtime, not fail loudly. Same undocumented-gap category
 * as the "Dictum has no dynamic collections yet" note in
 * SOURCE_OF_TRUTH_CNC_VIBECODER.md. Left out on purpose; flagged, not
 * silently worked around.
 *
 * Struct-out-param widgets (GuiScrollPanel, GuiColorPicker/Panel(HSV),
 * GuiGrid -- these take Vector2 pointer / Color pointer / Vector3
 * pointer out-params) are also not wrapped here for the same
 * address-of reason. They are a real, separate future addition, not
 * covered by this file.
 */

#define RAYGUI_IMPLEMENTATION
#include "raygui.h"

/* -- Toggle / checkbox (bool* out-param) -------------------------------- */

bool dictum_raygui_toggle(Rectangle bounds, const char *text, bool active_in) {
    bool active = active_in;
    GuiToggle(bounds, text, &active);
    return active;
}

bool dictum_raygui_checkbox(Rectangle bounds, const char *text, bool checked_in) {
    bool checked = checked_in;
    GuiCheckBox(bounds, text, &checked);
    return checked;
}

/* -- Index-based selection widgets (int* out-param) --------------------- */

int32_t dictum_raygui_toggle_group(Rectangle bounds, const char *text, int32_t active_in) {
    int active = (int)active_in;
    GuiToggleGroup(bounds, text, &active);
    return (int32_t)active;
}

int32_t dictum_raygui_toggle_slider(Rectangle bounds, const char *text, int32_t active_in) {
    int active = (int)active_in;
    GuiToggleSlider(bounds, text, &active);
    return (int32_t)active;
}

int32_t dictum_raygui_combo_box(Rectangle bounds, const char *text, int32_t active_in) {
    int active = (int)active_in;
    GuiComboBox(bounds, text, &active);
    return (int32_t)active;
}

int32_t dictum_raygui_dropdown_box(Rectangle bounds, const char *text, int32_t active_in, bool edit_mode) {
    int active = (int)active_in;
    GuiDropdownBox(bounds, text, &active, edit_mode);
    return (int32_t)active;
}

/* -- Numeric-entry widgets (int* out-param + min/max) -------------------- */

int32_t dictum_raygui_spinner(Rectangle bounds, const char *text, int32_t value_in,
                               int32_t min_value, int32_t max_value, bool edit_mode) {
    int value = (int)value_in;
    GuiSpinner(bounds, text, &value, (int)min_value, (int)max_value, edit_mode);
    return (int32_t)value;
}

int32_t dictum_raygui_value_box(Rectangle bounds, const char *text, int32_t value_in,
                                 int32_t min_value, int32_t max_value, bool edit_mode) {
    int value = (int)value_in;
    GuiValueBox(bounds, text, &value, (int)min_value, (int)max_value, edit_mode);
    return (int32_t)value;
}

/* -- Float-valued widgets (float* out-param) ----------------------------- */

float dictum_raygui_slider(Rectangle bounds, const char *text_left, const char *text_right,
                            float value_in, float min_value, float max_value) {
    float value = value_in;
    GuiSlider(bounds, text_left, text_right, &value, min_value, max_value);
    return value;
}

float dictum_raygui_slider_bar(Rectangle bounds, const char *text_left, const char *text_right,
                                float value_in, float min_value, float max_value) {
    float value = value_in;
    GuiSliderBar(bounds, text_left, text_right, &value, min_value, max_value);
    return value;
}

float dictum_raygui_progress_bar(Rectangle bounds, const char *text_left, const char *text_right,
                                  float value_in, float min_value, float max_value) {
    float value = value_in;
    GuiProgressBar(bounds, text_left, text_right, &value, min_value, max_value);
    return value;
}

float dictum_raygui_color_bar_alpha(Rectangle bounds, const char *text, float alpha_in) {
    float alpha = alpha_in;
    GuiColorBarAlpha(bounds, text, &alpha);
    return alpha;
}

float dictum_raygui_color_bar_hue(Rectangle bounds, const char *text, float value_in) {
    float value = value_in;
    GuiColorBarHue(bounds, text, &value);
    return value;
}
