// grep.cpp — C++ port of grep.py
//
// Build (MSVC):  cl /std:c++17 /EHsc /O2 grep.cpp /Fe:grep.exe
// Build (GCC):   g++ -std=c++17 -O2 -o grep grep.cpp
// Build (Clang): clang++ -std=c++17 -O2 -o grep grep.cpp

#include <algorithm>
#include <cctype>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <regex>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace fs = std::filesystem;

// ── Path encoding ───────────────────────────────────────────────────────
// Every path in this program is carried around as a narrow std::string holding
// UTF-8, and converted to fs::path only at the moment the filesystem is
// touched.  This matters on Windows: fs::path::string() converts wide -> the
// active ANSI code page and THROWS std::system_error for any character the code
// page can't represent (e.g. U+22C6 '*' in a filename under cp1252).  Using it
// in the directory listing meant one awkwardly-named file made grep silently
// report nothing at all for the entire directory, because the exception unwound
// past the whole search into main's catch-all.  u8string() never throws.
//
// Correspondingly, never hand a narrow path straight to ifstream on Windows --
// it would be interpreted as ANSI and fail to open these files.  Go through
// from_utf8() so the wide fs::path overload is used.

static std::string to_utf8(const fs::path& p) {
    auto s = p.u8string();                      // std::string in C++17,
    return std::string(s.begin(), s.end());     // std::u8string in C++20
}

static fs::path from_utf8(const std::string& s) {
    return fs::u8path(s);
}

// ── Signal handling ─────────────────────────────────────────────────────

static volatile sig_atomic_t g_interrupted = 0;
static void sigint_handler(int) { g_interrupted = 1; }

// ── String utilities ────────────────────────────────────────────────────

static std::string str_tolower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return (char)std::tolower(c); });
    return s;
}

static std::string rtrim(const std::string& s) {
    auto end = s.find_last_not_of(" \t\r\n\f\v");
    return end == std::string::npos ? "" : s.substr(0, end + 1);
}

static bool starts_with(const std::string& s, const std::string& pfx) {
    return s.size() >= pfx.size() && s.compare(0, pfx.size(), pfx) == 0;
}

static std::string remove_dot_prefix(const std::string& s) {
    if (starts_with(s, ".\\")) return s.substr(2);
    if (starts_with(s, "./"))  return s.substr(2);
    return s;
}

// Split "dir/spec" into (dir, spec).  Empty dir means no directory part.
static std::pair<std::string, std::string> split_filespec(const std::string& pf) {
    auto sep = pf.find_last_of("/\\");
    if (sep == std::string::npos) return {"", pf};
    return {pf.substr(0, sep), pf.substr(sep + 1)};
}

// ── Color system ────────────────────────────────────────────────────────

static const std::map<std::string, std::string> ANSI_COLORS = {
    {"black",           "\033[0;30m"},
    {"red",             "\033[0;31m"},
    {"green",           "\033[0;32m"},
    {"yellow",          "\033[0;33m"},
    {"blue",            "\033[0;34m"},
    {"magenta",         "\033[0;35m"},
    {"cyan",            "\033[0;36m"},
    {"white",           "\033[0;37m"},
    {"brightblack",     "\033[1;30m"},
    {"brightred",       "\033[1;31m"},
    {"brightgreen",     "\033[1;32m"},
    {"brightyellow",    "\033[1;33m"},
    {"brightblue",      "\033[1;34m"},
    {"brightmagenta",   "\033[1;35m"},
    {"brightcyan",      "\033[1;36m"},
    {"brightwhite",     "\033[1;37m"},
    {"default",         "\033[0m"},
};

struct FColors {
    std::string fncolor      = "brightgreen";
    std::string coloncolor   = "brightblack";
    std::string linecolor    = "brightred";
    std::string normalcolor  = "default";
    std::string errcolor     = "brightred";
    std::string esccolor     = "brightblue";
};

struct ResolvedColors {
    std::string fn, colon, line, normal, err, esc;
};

static const FColors DEFAULT_FCOLORS;

static std::string color_lookup(const std::string& name, bool use_colors) {
    if (!use_colors) return "";
    auto it = ANSI_COLORS.find(name);
    return it != ANSI_COLORS.end() ? it->second : "";
}

static ResolvedColors resolve(const FColors& fc, bool use_colors) {
    return {
        color_lookup(fc.fncolor,     use_colors),
        color_lookup(fc.coloncolor,  use_colors),
        color_lookup(fc.linecolor,   use_colors),
        color_lookup(fc.normalcolor, use_colors),
        color_lookup(fc.errcolor,    use_colors),
        color_lookup(fc.esccolor,    use_colors),
    };
}

#ifdef _WIN32
static bool enable_ansi() {
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD mode = 0;
    if (!GetConsoleMode(h, &mode)) return false;
    return SetConsoleMode(h, mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING) != 0;
}

static std::string wide_to_utf8(const wchar_t* w) {
    if (!w || !*w) return {};
    int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, nullptr, 0, nullptr, nullptr);
    if (n <= 1) return {};
    std::string out((size_t)n - 1, '\0');
    WideCharToMultiByte(CP_UTF8, 0, w, -1, out.data(), n, nullptr, nullptr);
    return out;
}

// Everything we print is UTF-8 (see the "Path encoding" note), so the console
// has to be told.  The previous code page is restored on the way out so we
// don't leave the user's console reconfigured behind us.
struct ConsoleCodePage {
    UINT saved = 0;
    ConsoleCodePage() : saved(GetConsoleOutputCP()) {
        if (saved != CP_UTF8) SetConsoleOutputCP(CP_UTF8);
    }
    ~ConsoleCodePage() {
        if (saved && saved != CP_UTF8) SetConsoleOutputCP(saved);
    }
};
#endif

// ── Config file (simple INI) ────────────────────────────────────────────

struct IniFile {
    std::map<std::string, std::map<std::string, std::string>> sections;

    bool load(const std::string& path) {
        std::ifstream f(from_utf8(path));
        if (!f) return false;
        std::string section, line;
        while (std::getline(f, line)) {
            line = rtrim(line);
            if (line.empty() || line[0] == '#' || line[0] == ';') continue;
            if (line.front() == '[' && line.back() == ']') {
                section = str_tolower(line.substr(1, line.size() - 2));
            } else {
                auto eq = line.find('=');
                if (eq != std::string::npos) {
                    std::string key = rtrim(str_tolower(line.substr(0, eq)));
                    std::string val = line.substr(eq + 1);
                    // ltrim val
                    auto vstart = val.find_first_not_of(" \t");
                    val = vstart == std::string::npos ? "" : val.substr(vstart);
                    sections[section][key] = val;
                }
            }
        }
        return true;
    }

    bool save(const std::string& path) const {
        std::ofstream f(from_utf8(path));
        if (!f) return false;
        for (auto& [sec, kvs] : sections) {
            f << "[" << sec << "]\n";
            for (auto& [k, v] : kvs) f << k << " = " << v << "\n";
            f << "\n";
        }
        return true;
    }

    bool get_bool(const std::string& sec, const std::string& key,
                  bool fallback) const {
        auto si = sections.find(sec);
        if (si == sections.end()) return fallback;
        auto ki = si->second.find(key);
        if (ki == si->second.end()) return fallback;
        auto v = str_tolower(ki->second);
        return v == "true" || v == "1" || v == "yes";
    }

    std::string get_str(const std::string& sec, const std::string& key,
                        const std::string& fallback = "") const {
        auto si = sections.find(sec);
        if (si == sections.end()) return fallback;
        auto ki = si->second.find(key);
        return ki == si->second.end() ? fallback : ki->second;
    }
};

// ── fnmatch ─────────────────────────────────────────────────────────────

static bool fnmatch_recursive(const std::string& pat, size_t pi,
                               const std::string& name, size_t ni) {
    while (pi < pat.size()) {
        char pc = pat[pi];
        if (pc == '*') {
            while (pi < pat.size() && pat[pi] == '*') ++pi;
            if (pi == pat.size()) return true;
            for (size_t k = ni; k <= name.size(); ++k)
                if (fnmatch_recursive(pat, pi, name, k)) return true;
            return false;
        } else if (pc == '?') {
            if (ni >= name.size()) return false;
            ++pi; ++ni;
        } else if (pc == '[') {
            if (ni >= name.size()) return false;
            char nc = name[ni];
            ++pi;
            bool negate = (pi < pat.size() && pat[pi] == '!');
            if (negate) ++pi;
            bool matched = false;
            while (pi < pat.size() && pat[pi] != ']') {
                char lo = pat[pi++];
                if (pi + 1 < pat.size() && pat[pi] == '-' && pat[pi + 1] != ']') {
                    ++pi;
                    char hi = pat[pi++];
                    if ((unsigned char)nc >= (unsigned char)lo &&
                        (unsigned char)nc <= (unsigned char)hi)
                        matched = true;
                } else {
                    if (nc == lo) matched = true;
                }
            }
            if (pi < pat.size()) ++pi;   // skip ']'
            if (negate) matched = !matched;
            if (!matched) return false;
            ++ni;
        } else {
            if (ni >= name.size() || name[ni] != pc) return false;
            ++pi; ++ni;
        }
    }
    return ni == name.size();
}

static bool fnmatch_match(const std::string& pattern, const std::string& name,
                           bool case_sensitive) {
    if (case_sensitive)
        return fnmatch_recursive(pattern, 0, name, 0);
    return fnmatch_recursive(str_tolower(pattern), 0, str_tolower(name), 0);
}

static bool any_fnmatch(const std::string& name,
                         const std::vector<std::string>& patterns,
                         bool case_sensitive) {
    for (auto& p : patterns)
        if (fnmatch_match(p, name, case_sensitive)) return true;
    return false;
}

// ── Path-parts helpers (for --x_paths matching) ─────────────────────────

using PathParts = std::vector<std::string>;

static PathParts to_parts(const std::string& p) {
    PathParts parts;
    for (auto& c : from_utf8(p))
        if (!c.empty()) parts.push_back(to_utf8(c));
    return parts;
}

static bool suffix_matches(const PathParts& haystack, const PathParts& needle) {
    if (needle.size() > haystack.size()) return false;
    return std::equal(needle.begin(), needle.end(),
                      haystack.end() - (ptrdiff_t)needle.size());
}

static bool suffix_matches_any(const PathParts& haystack,
                                const std::vector<PathParts>& needles) {
    for (auto& n : needles)
        if (suffix_matches(haystack, n)) return true;
    return false;
}

// ── Argument parsing ────────────────────────────────────────────────────

struct Args {
    std::string regex;
    bool has_regex = false;
    std::vector<std::string> files;           // positional files
    std::vector<std::string> expressions;     // -e
    int  proximity          = -1;             // -P  (-1 = not set)
    std::vector<std::string> f_files;         // -f
    bool f_specified        = false;
    bool dereference_recursive = false;       // -R
    bool recursive          = false;          // -r
    std::vector<std::string> paths;           // -p
    bool p_specified        = false;
    std::vector<std::string> x_files;         // --x_files
    std::vector<std::string> x_paths;         // --x_paths
    bool case_insensitive   = false;          // -i
    bool case_sensitive_fn  = false;          // -c
    bool dotall             = false;          // --dotall
    int  before_context     = -1;             // -B
    int  after_context      = -1;             // -A
    int  context            = -1;             // -C
    int  max_count          = -1;             // -m
    bool negate             = false;          // -L
    bool filenames_only     = false;          // -l
    bool line_numbers       = false;          // -n
    int  allow_match_colors = -1;             // --[no-]allow-match-colors
    int  colors_flag        = -1;             // --[no-]colors
    std::vector<std::string> set_colors;
    bool set_colors_specified = false;
    bool remember           = false;          // --remember
};

static void print_help() {
    std::cout <<
"usage: grep [regex] [files ...] [options]\n"
"\n"
"positional arguments:\n"
"  regex                    regular expression pattern to search for\n"
"  files                    search files matching these filename patterns\n"
"\n"
"options:\n"
"  -h, --help               show this help message and exit\n"
"  -e, --expression PATTERN specify additional regex patterns (repeatable).\n"
"                           ALL patterns must be present before any results are\n"
"                           shown for a file: without -P they must appear\n"
"                           somewhere in the file, with -P within the proximity\n"
"                           window. to match any of several alternatives\n"
"                           instead, put them in one regex separated by '|'\n"
"  -P, --proximity NUM      require all patterns to occur within NUM lines of\n"
"                           each other instead of anywhere in the file. only\n"
"                           matching lines inside a satisfying window are shown\n"
"  -f [PATTERN ...]         search files matching these filename patterns.\n"
"                           this option exists so you can search files even if\n"
"                           you don't specify a regex\n"
"  -R, --dereference-recursive\n"
"                           search directories recursively\n"
"  -r, --recursive          search directories recursively, ignoring symlinked\n"
"                           directories unless they're explicitly included\n"
"  -p [PATH ...]            search these paths\n"
"  --x_files [SPEC ...]     exclude these filename patterns from search\n"
"  --x_paths [PATH ...]     exclude these paths from search\n"
"  -i                       make search case-insensitive\n"
"  -c                       make filename matching case-sensitive regardless of\n"
"                           your system's standard\n"
"  --dotall                 make '.' match newlines\n"
"  -B, --before-context NUM print NUM lines of context preceding a match\n"
"  -A, --after-context NUM  print NUM lines of context following a match\n"
"  -C, --context NUM        print NUM lines of context before and after a match\n"
"  -m, --max-count NUM      maximum number of matches to show\n"
"  -L, --negate             show only files that contain no match\n"
"  -l                       show only filenames\n"
"  -n, --line-numbers       show line numbers\n"
"  --allow-match-colors     show ANSI colors if they exist in the match text\n"
"  --no-allow-match-colors  strip ANSI colors from match text\n"
"  --colors                 enable colorized output\n"
"  --no-colors              disable colorized output\n"
"  --set-colors [C C C C C C]\n"
"                           provide six color names to set the colors of\n"
"                           filenames, colons, line numbers, match contents,\n"
"                           error messages and escape codes. valid names:\n"
"                           black red green yellow blue magenta cyan white\n"
"                           brightblack brightred brightgreen brightyellow\n"
"                           brightblue brightmagenta brightcyan brightwhite\n"
"                           default.  no arguments to reset to defaults\n"
"  --remember               remember all color settings\n";
}

// Consume zero-or-more non-option values after a variadic flag.
static void consume_variadic(int argc, char* argv[], int& i,
                              std::vector<std::string>& out) {
    while (i + 1 < argc && argv[i + 1][0] != '-') {
        out.push_back(argv[++i]);
    }
}

static void parse_args(int argc, char* argv[], Args& args) {
    std::vector<std::string> positionals;

    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];

        if (a == "--") {
            for (++i; i < argc; ++i) positionals.push_back(argv[i]);
            break;
        }

        // ── long options ────────────────────────────────────────────
        if (starts_with(a, "--")) {
            if (a == "--help")                         { print_help(); std::exit(0); }
            else if (a == "--expression")              { if (++i < argc) args.expressions.push_back(argv[i]); }
            else if (a == "--proximity")               { if (++i < argc) args.proximity = std::stoi(argv[i]); }
            else if (a == "--dereference-recursive")    { args.dereference_recursive = true; }
            else if (a == "--recursive")                { args.recursive = true; }
            else if (a == "--x_files")                  { consume_variadic(argc, argv, i, args.x_files); }
            else if (a == "--x_paths")                  { consume_variadic(argc, argv, i, args.x_paths); }
            else if (a == "--dotall")                   { args.dotall = true; }
            else if (a == "--before-context")           { if (++i < argc) args.before_context = std::stoi(argv[i]); }
            else if (a == "--after-context")            { if (++i < argc) args.after_context  = std::stoi(argv[i]); }
            else if (a == "--context")                  { if (++i < argc) args.context = std::stoi(argv[i]); }
            else if (a == "--max-count")                { if (++i < argc) args.max_count = std::stoi(argv[i]); }
            else if (a == "--negate")                   { args.negate = true; }
            else if (a == "--line-numbers")             { args.line_numbers = true; }
            else if (a == "--allow-match-colors")       { args.allow_match_colors = 1; }
            else if (a == "--no-allow-match-colors")    { args.allow_match_colors = 0; }
            else if (a == "--colors")                   { args.colors_flag = 1; }
            else if (a == "--no-colors")                { args.colors_flag = 0; }
            else if (a == "--set-colors") {
                args.set_colors_specified = true;
                consume_variadic(argc, argv, i, args.set_colors);
            }
            else if (a == "--remember")                 { args.remember = true; }
            else {
                std::cerr << "Unknown option: " << a << "\n";
                std::exit(1);
            }
            continue;
        }

        // ── short options (may be combined, e.g. -ilrn) ─────────────
        if (a.size() > 1 && a[0] == '-') {
            for (size_t j = 1; j < a.size(); ++j) {
                char ch = a[j];
                switch (ch) {
                case 'h': print_help(); std::exit(0);
                case 'i': args.case_insensitive = true;  break;
                case 'c': args.case_sensitive_fn = true;  break;
                case 'l': args.filenames_only   = true;  break;
                case 'n': args.line_numbers     = true;  break;
                case 'r': args.recursive        = true;  break;
                case 'R': args.dereference_recursive = true; break;
                case 'L': args.negate           = true;  break;

                // flags that take a value: rest of this arg or next arg
                case 'e': {
                    std::string val;
                    if (j + 1 < a.size()) val = a.substr(j + 1);
                    else if (i + 1 < argc) val = argv[++i];
                    args.expressions.push_back(val);
                    goto next_arg;
                }
                case 'P': {
                    std::string val;
                    if (j + 1 < a.size()) val = a.substr(j + 1);
                    else if (i + 1 < argc) val = argv[++i];
                    args.proximity = std::stoi(val);
                    goto next_arg;
                }
                case 'B': {
                    std::string val;
                    if (j + 1 < a.size()) val = a.substr(j + 1);
                    else if (i + 1 < argc) val = argv[++i];
                    args.before_context = std::stoi(val);
                    goto next_arg;
                }
                case 'A': {
                    std::string val;
                    if (j + 1 < a.size()) val = a.substr(j + 1);
                    else if (i + 1 < argc) val = argv[++i];
                    args.after_context = std::stoi(val);
                    goto next_arg;
                }
                case 'C': {
                    std::string val;
                    if (j + 1 < a.size()) val = a.substr(j + 1);
                    else if (i + 1 < argc) val = argv[++i];
                    args.context = std::stoi(val);
                    goto next_arg;
                }
                case 'm': {
                    std::string val;
                    if (j + 1 < a.size()) val = a.substr(j + 1);
                    else if (i + 1 < argc) val = argv[++i];
                    args.max_count = std::stoi(val);
                    goto next_arg;
                }

                // variadic flags (rest of this arg is first value)
                case 'f':
                    args.f_specified = true;
                    if (j + 1 < a.size())
                        args.f_files.push_back(a.substr(j + 1));
                    consume_variadic(argc, argv, i, args.f_files);
                    goto next_arg;
                case 'p':
                    args.p_specified = true;
                    if (j + 1 < a.size())
                        args.paths.push_back(a.substr(j + 1));
                    consume_variadic(argc, argv, i, args.paths);
                    goto next_arg;

                default:
                    std::cerr << "Unknown option: -" << ch << "\n";
                    std::exit(1);
                }
            }
        next_arg:
            continue;
        }

        // positional
        positionals.push_back(a);
    }

    // assign positionals: first is regex, rest are files
    if (!positionals.empty()) {
        args.regex = positionals[0];
        args.has_regex = true;
        for (size_t j = 1; j < positionals.size(); ++j)
            args.files.push_back(positionals[j]);
    }
}

// ── Dotall regex transformation ─────────────────────────────────────────
// ECMAScript regex has no dotall flag; replace unescaped '.' outside
// character classes with [\s\S] so '.' matches newlines.

static std::string make_dotall_pattern(const std::string& pat) {
    std::string out;
    bool in_class = false, escaped = false;
    for (char ch : pat) {
        if (escaped)                          { out += ch; escaped = false; }
        else if (ch == '\\')                  { out += ch; escaped = true;  }
        else if (ch == '[' && !in_class)      { in_class = true;  out += ch; }
        else if (ch == ']' &&  in_class)      { in_class = false; out += ch; }
        else if (ch == '.' && !in_class)      { out += "[\\s\\S]"; }
        else                                  { out += ch; }
    }
    return out;
}

// ═══════════════════════════════════════════════════════════════════════
//  Global state
// ═══════════════════════════════════════════════════════════════════════

static Args          g_args;
static FColors        g_fcolors;
static ResolvedColors g_c;
static bool           g_use_colors          = true;
static bool           g_allow_match_colors  = false;
#ifdef _WIN32
static bool           g_case_sensitive_fn   = false;   // Windows default
#else
static bool           g_case_sensitive_fn   = true;    // POSIX default
#endif
static std::vector<std::regex> g_regexes;
static int            g_before_ctx          = 0;
static int            g_after_ctx           = 0;

static std::vector<std::string> g_i_files;
static std::vector<std::string> g_i_paths;
static std::vector<std::string> g_x_files;
static std::vector<PathParts>   g_x_path_parts;
static std::vector<PathParts>   g_i_path_parts;

static std::set<std::string>    g_processed;
static const int                MAX_ERR = 5;

// ── Escape-character filter ─────────────────────────────────────────────

static std::string filter_escapes(const std::string& s) {
    std::string out;
    out.reserve(s.size());
    for (size_t i = 0; i < s.size(); ++i) {
        auto ch = static_cast<unsigned char>(s[i]);

        // Determine if this byte is a control character we should visualise.
        bool is_ctrl;
        if (g_allow_match_colors) {
            // Filter control chars except LF(0a), CR(0d), ESC(1b)
            is_ctrl = (ch <= 0x09) || (ch >= 0x0b && ch <= 0x0c) ||
                      (ch >= 0x0e && ch <= 0x1a) || (ch >= 0x1c && ch <= 0x1f);
        } else {
            // Filter control chars except LF(0a) and CR(0d)
            is_ctrl = (ch <= 0x09) || (ch >= 0x0b && ch <= 0x0c) ||
                      (ch >= 0x0e && ch <= 0x1f);
        }

        if (is_ctrl) {
            char hex[8];
            std::snprintf(hex, sizeof hex, "\\x%02x", ch);
            out += g_c.esc;
            out += hex;
            out += g_c.normal;
        } else if (ch == 0x1b && g_allow_match_colors) {
            // ESC: pass through if it's a valid ANSI color sequence
            if (i + 1 < s.size() && s[i + 1] == '[') {
                size_t j = i + 2;
                while (j < s.size() &&
                       (std::isdigit((unsigned char)s[j]) || s[j] == ';'))
                    ++j;
                if (j < s.size() && s[j] == 'm') {
                    out.append(s, i, j - i + 1);
                    i = j;
                    continue;
                }
            }
            // Not a colour code – show hex
            char hex[8];
            std::snprintf(hex, sizeof hex, "\\x%02x", ch);
            out += g_c.esc;
            out += hex;
            out += g_c.normal;
        } else {
            out += static_cast<char>(ch);
        }
    }
    return out;
}

// ── Output helpers ──────────────────────────────────────────────────────

// Print filename only (for -l / -L / no-regex mode).
static void prn_filename(const std::string& p) {
    std::cout << g_c.normal << p << "\n";
}

// Print a result line:  filename[:lineno]:text
static void prn(const std::string& p, int lineno, const std::string& raw) {
    std::string text = filter_escapes(rtrim(raw));
    std::cout << g_c.fn << p;
    if (g_args.line_numbers && lineno > 0)
        std::cout << g_c.colon << ":" << g_c.line << lineno << g_c.colon << ":";
    else
        std::cout << g_c.colon << ":";
    std::cout << g_c.normal << text << "\n";
}

// ── Directory listing ───────────────────────────────────────────────────

static std::vector<std::string> ld(const std::string& directory) {
    std::error_code ec;
    fs::path dirp = from_utf8(directory);
    if (!fs::exists(dirp, ec)) {
        std::cout << g_c.err << "directory doesn't exist: "
                  << g_c.normal << directory << "\n";
        return {};
    }
    if (!fs::is_directory(dirp, ec)) {
        std::cout << g_c.err << "is not a directory: "
                  << g_c.normal << directory << "\n";
        return {};
    }
    std::vector<std::string> entries;
    try {
        // Skip unreadable subentries rather than aborting the whole listing.
        auto it = fs::directory_iterator(
            dirp, fs::directory_options::skip_permission_denied);
        for (auto& de : it)
            entries.push_back(to_utf8(de.path().filename()));
    } catch (const fs::filesystem_error&) {
        std::cout << g_c.err << "Permission denied: "
                  << g_c.normal << directory << "\n";
    } catch (const std::exception& e) {
        // Never let a listing failure escape: it would unwind past the entire
        // search and produce a silent empty result.
        std::cout << g_c.err << "Error listing directory: "
                  << g_c.normal << directory << g_c.err << " (" << e.what() << ")\n";
    }
    return entries;
}

// ── Filespec probe (diagnostics only) ───────────────────────────────────
// How many existing files 'pattern' matches when treated as a filespec, or -1
// if it can't be tried.  Used only to explain a regex compile failure: the
// positional argument fills the 'regex' slot before 'files', so when every
// pattern was supplied with -e a lone trailing filespec gets compiled as a
// regex and fails for reasons that look unrelated to what the user typed (e.g.
// "bad escape \m" for a Windows path).  Deliberately silent -- unlike ld(),
// this must not print "directory doesn't exist" while merely guessing.

static long filespec_hit_count(const std::string& pattern) {
    auto [dir, spec] = split_filespec(pattern);
    if (spec.empty()) return -1;
    if (dir.empty()) dir = ".";
    std::error_code ec;
    fs::path dirp = from_utf8(dir);
    if (!fs::is_directory(dirp, ec)) return -1;
    long hits = 0;
    try {
        auto it = fs::directory_iterator(
            dirp, fs::directory_options::skip_permission_denied, ec);
        if (ec) return -1;
        for (auto& de : it)
            if (fnmatch_match(spec, to_utf8(de.path().filename()), g_case_sensitive_fn))
                ++hits;
    } catch (const std::exception&) {
        return -1;
    }
    return hits;
}

// Explain that 'pattern' was consumed as the search regex, and how to pass it as
// a filespec instead.  Only called when it demonstrably names files.
static void print_slot_hint(const std::string& pattern, long hits) {
    std::cout << g_c.normal << "It matches " << hits << " existing file"
              << (hits == 1 ? "" : "s")
              << ", but the first non-option argument is always the\n"
                 "search regex -- even when every pattern was given with -e. "
                 "Pass filename patterns with -f:\n"
                 "  grep";
    for (auto& x : g_args.expressions) std::cout << " -e " << x;
    std::cout << " -f \"" << pattern << "\"\n";
}

// ── Recursive walk ──────────────────────────────────────────────────────

using WalkCB = std::function<void(const std::string& /*path*/,
                                   const std::string& /*filename*/)>;

static std::set<PathParts> g_sparts;

static void walk(const std::string& directory, PathParts parts, WalkCB cb) {
    if (g_interrupted) return;
    if (g_sparts.count(parts)) return;

    for (auto& fn : ld(directory)) {
        if (g_interrupted) return;
        fs::path joined = from_utf8(directory) / from_utf8(fn);
        std::string p = to_utf8(joined);
        std::error_code ec;
        if (fs::is_regular_file(joined, ec)) {  // follows symlinks (matches os.path.isfile)
            cb(p, fn);
        } else if (fs::is_directory(joined, ec)) {
            PathParts parts2 = parts;
            parts2.push_back(fn);

            // With -r, skip symlinked directories unless explicitly in -p
            if (g_args.recursive && fs::is_symlink(fs::symlink_status(joined, ec)) &&
                !suffix_matches_any(parts2, g_i_path_parts)) {
                continue;
            }
            // Honour --x_paths
            if (suffix_matches_any(parts2, g_x_path_parts))
                continue;

            walk(p, parts2, cb);
        }
    }
    g_sparts.insert(std::move(parts));
}

// ── Whole-file AND gate ─────────────────────────────────────────────────
// Consume a line-based stream and report whether every compiled regex matched
// somewhere in it.  Bails out as soon as the last outstanding pattern is found,
// so files that do satisfy the gate usually aren't read to the end.
//
// This always gives the honest answer, including for a single pattern.  Do NOT
// add a "g_regexes.size() < 2 -> return true" shortcut here: -l/-L call this as
// their *only* match test, so short-circuiting makes single-pattern -l list
// every file and -L list none.  Callers that follow up with a per-line pass
// (the full-output path) skip this call themselves when there's only one
// pattern, because that later pass does the real filtering.

static bool all_present_lines(std::ifstream& inf) {
    std::set<size_t> unmatched;
    for (size_t i = 0; i < g_regexes.size(); ++i) unmatched.insert(i);
    std::string line;
    while (!unmatched.empty() && std::getline(inf, line)) {
        if (g_interrupted) return false;
        for (auto it = unmatched.begin(); it != unmatched.end(); ) {
            if (std::regex_search(line, g_regexes[*it])) it = unmatched.erase(it);
            else ++it;
        }
    }
    return unmatched.empty();
}

// ── Main search logic (process one file) ────────────────────────────────

static void process(std::string path) {
    path = remove_dot_prefix(path);
    if (g_processed.count(path)) return;
    g_processed.insert(path);

    if (g_regexes.empty()) {
        // No regex — just list the file.
        prn_filename(path);
        return;
    }

    std::ifstream inf(from_utf8(path), std::ios::binary);
    if (!inf) {
        std::cout << g_c.err << "Permission denied: "
                  << g_c.normal << path << "\n";
        return;
    }

    // ── dotall mode ─────────────────────────────────────────────────
    if (g_args.dotall) {
        std::string data;
        try {
            data.assign(std::istreambuf_iterator<char>(inf),
                        std::istreambuf_iterator<char>());
        } catch (const std::bad_alloc&) {
            std::cout << g_c.err << "Out of memory: "
                      << g_c.normal << path << "\n";
            return;
        }
        // --dotall reads the whole file at once, so the gate is always whole-file.
        bool present = true;
        for (auto& rc : g_regexes)
            if (!std::regex_search(data, rc)) { present = false; break; }
        if (g_args.negate) {
            if (!present) prn_filename(path);
        } else if (g_args.filenames_only) {
            if (present) prn_filename(path);
        } else if (present) {
            for (auto& rc : g_regexes) {
                auto beg = std::sregex_iterator(data.begin(), data.end(), rc);
                auto end = std::sregex_iterator();
                for (auto it = beg; it != end; ++it)
                    prn(path, -1, (*it)[0].str());
            }
        }
        return;
    }

    // ── line-by-line modes ──────────────────────────────────────────
    std::string line;
    int line_number = 0;

    // ── filenames-only / negate (no content output) ─────────────────
    if (g_args.filenames_only || g_args.negate) {
        if (g_args.proximity >= 0) {
            // Proximity: all patterns within window
            std::map<int, int> last_match;
            while (std::getline(inf, line)) {
                if (g_interrupted) return;
                ++line_number;
                for (int idx = 0; idx < (int)g_regexes.size(); ++idx)
                    if (std::regex_search(line, g_regexes[idx]))
                        last_match[idx] = line_number;
                // expire
                for (auto it = last_match.begin(); it != last_match.end(); )
                    it = (line_number - it->second >= g_args.proximity)
                             ? last_match.erase(it) : std::next(it);
                if ((int)last_match.size() == (int)g_regexes.size()) {
                    if (g_args.filenames_only) prn_filename(path);
                    return;   // found a proximity match
                }
            }
            // Reached EOF without proximity match
            if (g_args.negate) prn_filename(path);
        } else {
            // Whole-file gate: every pattern must appear somewhere.
            bool found = all_present_lines(inf);
            if (g_interrupted) return;
            if (found && g_args.filenames_only) prn_filename(path);
            if (!found && g_args.negate)        prn_filename(path);
        }
        return;
    }

    // ── full output mode ────────────────────────────────────────────
    // Print matching lines plus -B/-A/-C context.  The gate scope is the only
    // thing that varies: a sliding window with -P, otherwise the whole file.
    int num_matches       = 0;
    int last_printed_line = 0;
    int after_remaining   = 0;
    bool matched_one      = false;

    // Print one line, inserting a ----- separator when it isn't contiguous with
    // the previously printed line.  Separators only make sense when context was
    // requested -- without -B/-A/-C every printed line is itself a match, so a
    // separator between each pair would just be noise (and plain grep doesn't
    // print them either).  Keeping this conditional is what makes "-P >= the
    // file's length" produce byte-identical output to the whole-file gate.
    auto emit = [&](int ln, const std::string& text) {
        if (matched_one && ln > last_printed_line + 1 &&
            (g_before_ctx || g_after_ctx))
            std::cout << "-----\n";
        prn(path, ln, text);
        last_printed_line = ln;
        matched_one = true;
    };

    if (g_args.proximity >= 0) {
        // Gate scope is a sliding window.  Only matching lines inside a
        // satisfied window get printed, each expanded by before/after context --
        // the lines merely *between* two matches are not printed unless context
        // reaches them.
        int buf_size = g_args.proximity + g_before_ctx + 1;
        std::deque<std::tuple<int, std::string, bool>> prox_buf;
        std::map<int, int> last_match;

        while (std::getline(inf, line)) {
            if (g_interrupted) return;
            ++line_number;

            bool any_hit = false;
            for (int idx = 0; idx < (int)g_regexes.size(); ++idx)
                if (std::regex_search(line, g_regexes[idx])) {
                    last_match[idx] = line_number;
                    any_hit = true;
                }

            prox_buf.push_back({line_number, line, any_hit});
            if ((int)prox_buf.size() > buf_size)
                prox_buf.pop_front();

            // expire matches that have fallen outside the proximity window
            for (auto it = last_match.begin(); it != last_match.end(); )
                it = (line_number - it->second >= g_args.proximity)
                         ? last_match.erase(it) : std::next(it);

            if ((int)last_match.size() == (int)g_regexes.size()) {
                ++num_matches;
                if (g_args.max_count >= 0 && num_matches > g_args.max_count)
                    break;
                // The satisfied window runs from the earliest live match to the
                // current line.  max(last_match) is always line_number: the set
                // can only *become* complete on a line where a pattern matched.
                int min_ln = line_number;
                for (auto& [_, ln] : last_match)
                    min_ln = std::min(min_ln, ln);

                std::set<int> wanted;
                for (auto& [bln, bline, bmatch] : prox_buf)
                    if (bmatch && bln >= min_ln && bln <= line_number)
                        for (int x = std::max(bln - g_before_ctx, 1);
                             x <= bln + g_after_ctx; ++x)
                            wanted.insert(x);

                for (auto& [bln, bline, bmatch] : prox_buf)
                    if (wanted.count(bln) && bln > last_printed_line)
                        emit(bln, bline);

                // after-context past the completing match is still unread,
                // so stream it
                after_remaining = g_after_ctx;
                last_match.clear();
            } else if (after_remaining > 0 && line_number > last_printed_line) {
                emit(line_number, line);
                --after_remaining;
            }
        }
    } else {
        // Gate scope is the whole file: require every pattern before printing
        // anything.  Done as a separate pass rather than a giant proximity
        // window so memory stays O(1).  With a single pattern the gate can't
        // reject anything the per-line loop below wouldn't also skip, so the
        // extra pass is pure cost and is skipped.
        if (g_regexes.size() > 1) {
            if (!all_present_lines(inf)) return;
            if (g_interrupted) return;
            inf.clear();
            inf.seekg(0);
            line_number = 0;
        }

        if (g_before_ctx || g_after_ctx) {
            // Context-aware search
            std::deque<std::pair<int, std::string>> before_buf;

            while (std::getline(inf, line)) {
                if (g_interrupted) return;
                ++line_number;

                bool m = false;
                for (auto& rc : g_regexes)
                    if (std::regex_search(line, rc)) { m = true; break; }

                if (m) {
                    ++num_matches;
                    if (g_args.max_count >= 0 && num_matches > g_args.max_count)
                        break;

                    int start = std::max(line_number - g_before_ctx,
                                         last_printed_line + 1);

                    // Print before-context lines not yet printed
                    for (auto& [bln, bline] : before_buf)
                        if (bln >= start && bln > last_printed_line)
                            emit(bln, bline);

                    // Print the match line itself
                    if (line_number > last_printed_line)
                        emit(line_number, line);

                    after_remaining = g_after_ctx;
                } else if (after_remaining > 0) {
                    emit(line_number, line);
                    --after_remaining;
                }

                // Maintain before-context buffer
                before_buf.push_back({line_number, line});
                if ((int)before_buf.size() > g_before_ctx)
                    before_buf.pop_front();
            }
        } else {
            // Simple (no context); emit() suppresses separators in this case
            while (std::getline(inf, line)) {
                if (g_interrupted) return;
                ++line_number;
                bool m = false;
                for (auto& rc : g_regexes)
                    if (std::regex_search(line, rc)) { m = true; break; }
                if (m) {
                    ++num_matches;
                    if (g_args.max_count >= 0 && num_matches > g_args.max_count)
                        break;
                    emit(line_number, line);
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  main
// ═══════════════════════════════════════════════════════════════════════

static int run(int argc, char* argv[]) {
    std::signal(SIGINT, sigint_handler);

    if (argc == 1) { print_help(); return 0; }

    parse_args(argc, argv, g_args);

    // ── Resolve config-file path (same directory as executable) ─────
    std::string config_path;
    {
#ifdef _WIN32
        wchar_t exe[MAX_PATH]{};
        GetModuleFileNameW(nullptr, exe, MAX_PATH);
        config_path = to_utf8(fs::path(exe).parent_path() / "grep.colors.conf");
#else
        std::error_code ec;
        auto exepath = fs::read_symlink("/proc/self/exe", ec);
        if (ec) exepath = fs::absolute(argv[0], ec);
        config_path = to_utf8(exepath.parent_path() / "grep.colors.conf");
#endif
    }

    // ── Colour initialisation ───────────────────────────────────────
    g_fcolors = DEFAULT_FCOLORS;
    g_use_colors = (g_args.colors_flag == -1) ? true : (g_args.colors_flag == 1);
    g_allow_match_colors = false;

    IniFile ini;
    bool config_loaded = false;
    {
        std::error_code ec;
        if (fs::is_regular_file(config_path, ec)) {
            if (ini.load(config_path)) {
                config_loaded = true;
                if (!g_args.set_colors_specified) {
                    // Load saved colour names (only when --set-colors NOT given)
                    auto& cs = ini.sections["colors"];
                    if (!cs.empty()) {
                        auto get = [&](const char* k, std::string& dst) {
                            auto it = cs.find(k);
                            if (it != cs.end()) dst = it->second;
                        };
                        get("fncolor",     g_fcolors.fncolor);
                        get("coloncolor",  g_fcolors.coloncolor);
                        get("linecolor",   g_fcolors.linecolor);
                        get("normalcolor", g_fcolors.normalcolor);
                        get("errcolor",    g_fcolors.errcolor);
                        get("esccolor",    g_fcolors.esccolor);
                    }
                }
                if (g_args.colors_flag == -1)
                    g_use_colors = ini.get_bool("general", "use_colors", true);
                if (g_args.allow_match_colors == -1)
                    g_allow_match_colors =
                        ini.get_bool("general", "allow_match_colors", false);
            }
        }
    }

    // Override allow_match_colors from command-line
    if (g_args.allow_match_colors == 1)      g_allow_match_colors = true;
    else if (g_args.allow_match_colors == 0)  g_allow_match_colors = false;

#ifdef _WIN32
    if (g_use_colors && !enable_ansi()) {
        g_use_colors = false;
        std::cout << "ANSI color support unavailable on this terminal.\n\n";
    }
#endif

    // --set-colors handling
    if (g_args.set_colors_specified) {
        if (g_args.set_colors.empty()) {
            // Reset to defaults
            g_fcolors = DEFAULT_FCOLORS;
            g_use_colors = true;
        } else if (g_args.set_colors.size() != 6) {
            // Resolve colours enough to print the error in colour
            g_c = resolve(g_fcolors, g_use_colors);
            std::cout << g_c.err << "Error: " << g_c.normal
                      << "wrong number of colors (expected 6, got "
                      << g_args.set_colors.size() << ")\n";
            return 1;
        } else {
            for (auto& cn : g_args.set_colors) {
                if (ANSI_COLORS.find(cn) == ANSI_COLORS.end()) {
                    g_c = resolve(g_fcolors, g_use_colors);
                    std::cout << g_c.err << "Error: " << g_c.normal
                              << "invalid color name: " << cn << "\n";
                    return 1;
                }
            }
            g_fcolors.fncolor     = g_args.set_colors[0];
            g_fcolors.coloncolor  = g_args.set_colors[1];
            g_fcolors.linecolor   = g_args.set_colors[2];
            g_fcolors.normalcolor = g_args.set_colors[3];
            g_fcolors.errcolor    = g_args.set_colors[4];
            g_fcolors.esccolor    = g_args.set_colors[5];
        }
    }

    g_c = resolve(g_fcolors, g_use_colors);

    // --remember
    bool saved_conf = false;
    if (g_args.remember) {
        IniFile out;
        out.sections["general"]["use_colors"] =
            (g_args.colors_flag == -1) ? (g_use_colors ? "True" : "False")
                                       : (g_args.colors_flag ? "True" : "False");
        out.sections["general"]["allow_match_colors"] =
            g_allow_match_colors ? "True" : "False";
        out.sections["colors"]["fncolor"]     = g_fcolors.fncolor;
        out.sections["colors"]["coloncolor"]  = g_fcolors.coloncolor;
        out.sections["colors"]["linecolor"]   = g_fcolors.linecolor;
        out.sections["colors"]["normalcolor"] = g_fcolors.normalcolor;
        out.sections["colors"]["errcolor"]    = g_fcolors.errcolor;
        out.sections["colors"]["esccolor"]    = g_fcolors.esccolor;
        saved_conf = out.save(config_path);
    }

    // ── Filename case-sensitivity ───────────────────────────────────
    if (g_args.case_sensitive_fn)
        g_case_sensitive_fn = true;

    // ── dotall disables line numbers ────────────────────────────────
    if (g_args.dotall)
        g_args.line_numbers = false;

    // ── Context ─────────────────────────────────────────────────────
    g_before_ctx = (g_args.before_context >= 0) ? g_args.before_context : 0;
    g_after_ctx  = (g_args.after_context  >= 0) ? g_args.after_context  : 0;
    if (g_args.context >= 0)
        g_before_ctx = g_after_ctx = g_args.context;

    // ── Compile regex patterns ──────────────────────────────────────
    std::vector<std::string> all_patterns;
    if (g_args.has_regex)
        all_patterns.push_back(g_args.regex);
    for (auto& e : g_args.expressions)
        all_patterns.push_back(e);

    auto flags = std::regex_constants::ECMAScript | std::regex_constants::optimize;
    if (g_args.case_insensitive)
        flags |= std::regex_constants::icase;

    for (size_t pi = 0; pi < all_patterns.size(); ++pi) {
        const std::string& pat = all_patterns[pi];
        std::string effective = g_args.dotall ? make_dotall_pattern(pat) : pat;
        try {
            g_regexes.emplace_back(effective, flags);
        } catch (const std::regex_error& e) {
            std::cout << g_c.err << "Regex pattern error in '" << pat << "': "
                      << g_c.normal << e.what() << "\n";
            // all_patterns[0] is the positional argument whenever one was given.  Only
            // recommend -f when the argument demonstrably names files -- otherwise it's
            // just a broken regex and telling the user to pass it as a filespec would be
            // actively wrong.
            if (pi == 0 && g_args.has_regex) {
                long hits = filespec_hit_count(pat);
                if (hits > 0) {
                    print_slot_hint(pat, hits);
                } else if (!g_args.expressions.empty()) {
                    std::cout << g_c.err << "Note: " << g_c.normal
                              << "all your patterns were given with -e, so this argument "
                                 "was taken as the\n"
                                 "search regex. If you meant it as a filename pattern, "
                                 "pass it with -f.\n";
                }
            }
            return 1;
        }
    }

    // The same trap, but for a filespec that happens to compile as a valid regex.  The
    // ECMAScript engine accepts unknown escapes like \m as literals, so a Windows path
    // compiles fine here and the search just runs with a nonsense pattern and reports
    // nothing -- a silent wrong answer.  Warn when the positional names real files AND no
    // filespec was supplied by any other means; that last condition is what keeps the
    // documented `grep "class" -e "def" *.py` usage quiet, since there files is non-empty.
    if (g_args.has_regex && !g_args.expressions.empty() &&
        g_args.files.empty() && g_args.f_files.empty()) {
        long hits = filespec_hit_count(g_args.regex);
        if (hits > 0) {
            std::cout << g_c.err << "Warning: " << g_c.normal << "'" << g_args.regex
                      << "' is being used as the search regex.\n";
            print_slot_hint(g_args.regex, hits);
            std::cout << "\n";
        }
    }

    // ── Build file / path lists ─────────────────────────────────────
    g_i_files = g_args.files;
    for (auto& f : g_args.f_files)
        g_i_files.push_back(f);
    if (g_i_files.empty())
        g_i_files.push_back("*");

    g_i_paths = g_args.paths.empty()
                    ? std::vector<std::string>{"."} : g_args.paths;
    g_x_files = g_args.x_files;

    for (auto& xp : g_args.x_paths)
        g_x_path_parts.push_back(to_parts(xp));
    for (auto& ip : g_i_paths)
        g_i_path_parts.push_back(to_parts(ip));

    // ── Early exit when nothing useful is specified ──────────────────
    if (g_regexes.empty() && !g_args.p_specified &&
        g_args.x_files.empty() && g_args.x_paths.empty() &&
        g_args.files.empty() && !g_args.f_specified &&
        !g_args.filenames_only && !g_args.recursive &&
        !g_args.dereference_recursive) {
        return 0;
    }

    // ═════════════════════════════════════════════════════════════════
    //  File traversal
    // ═════════════════════════════════════════════════════════════════

    auto match_file = [&](const std::string& fn,
                           const std::vector<std::string>& specs) {
        return any_fnmatch(fn, specs, g_case_sensitive_fn);
    };
    auto excluded_file = [&](const std::string& fn) {
        return any_fnmatch(fn, g_x_files, g_case_sensitive_fn);
    };

    try {
        // true once a path-qualified "dir/spec" filespec has been handled
        bool had_dir_spec = false;
        std::vector<std::string> i_files2;

        if (g_args.recursive || g_args.dereference_recursive) {
            // ── Recursive mode ──────────────────────────────────────
            for (auto& pf : g_i_files) {
                if (g_interrupted) break;
                auto [dir, spec] = split_filespec(pf);
                if (!dir.empty()) {
                    if (spec.empty()) {
                        std::cout << g_c.err << "invalid filespec: "
                                  << g_c.normal << pf << "\n";
                    } else {
                        g_sparts.clear();
                        walk(dir, {dir}, [&](const std::string& p,
                                              const std::string& fn) {
                            if (fnmatch_match(spec, fn, g_case_sensitive_fn) &&
                                !excluded_file(fn))
                                process(p);
                        });
                        g_sparts.clear();
                        had_dir_spec = true;
                    }
                } else {
                    i_files2.push_back(spec);
                }
            }
            if (!had_dir_spec && i_files2.empty())
                i_files2.push_back("*");

            for (auto& ip : g_i_paths) {
                if (g_interrupted) break;
                walk(ip, {ip}, [&](const std::string& p,
                                    const std::string& fn) {
                    if (match_file(fn, i_files2) && !excluded_file(fn))
                        process(p);
                });
            }
        } else {
            // ── Non-recursive mode ──────────────────────────────────
            for (auto& pf : g_i_files) {
                if (g_interrupted) break;
                auto [dir, spec] = split_filespec(pf);
                if (!dir.empty()) {
                    if (spec.empty()) {
                        std::cout << g_c.err << "invalid filespec: "
                                  << g_c.normal << pf << "\n";
                    } else {
                        for (auto& fn : ld(dir)) {
                            fs::path fjoined = from_utf8(dir) / from_utf8(fn);
                            std::string fp = to_utf8(fjoined);
                            std::error_code ec;
                            if (!fs::is_directory(fjoined, ec) &&
                                fnmatch_match(spec, fn, g_case_sensitive_fn) &&
                                !excluded_file(fn))
                                process(fp);
                        }
                        had_dir_spec = true;
                    }
                } else {
                    i_files2.push_back(spec);
                }
            }
            // Only fall back to "*" when no filespec at all was given.  A
            // path-qualified filespec (dir/spec) has already been handled above,
            // so defaulting to "*" here would additionally scan g_i_paths
            // (default ".") and report unrelated files from the current directory.
            if (!had_dir_spec && i_files2.empty())
                i_files2.push_back("*");

            for (auto& ip : g_i_paths) {
                if (g_interrupted) break;
                for (auto& fn : ld(ip)) {
                    fs::path fjoined = from_utf8(ip) / from_utf8(fn);
                    std::string fp = to_utf8(fjoined);
                    std::error_code ec;
                    if (!fs::is_directory(fjoined, ec) &&
                        match_file(fn, i_files2) && !excluded_file(fn))
                        process(fp);
                }
            }
        }

        if (g_processed.empty() && !g_interrupted)
            std::cout << "No files matched your criteria.\n";

    } catch (const std::exception& e) {
        // Report rather than swallow. A silent catch-all here is what turned a
        // filename-encoding throw into "grep found nothing", with no clue why.
        std::cout << g_c.err << "Unexpected error: " << g_c.normal << e.what() << "\n";
    } catch (...) {
        std::cout << g_c.err << "Unexpected error." << g_c.normal << "\n";
    }

    // ── Ctrl+C banner ───────────────────────────────────────────────
    if (g_interrupted) {
        std::string mag = g_use_colors ? "\033[0;35m" : "";
        std::cout << "\n" << mag << "^C\n";
    }

    // ── Post-run messages ───────────────────────────────────────────
    if (saved_conf) {
        std::cout << "\n" << g_c.normal
                  << "Color settings were saved to \"" << config_path << "\"\n";
    } else if (g_args.remember) {
        std::cout << g_c.normal
                  << "Failed to save color settings to \""
                  << config_path << "\"\n";
    }

    // Reset terminal colour
    if (g_use_colors) std::cout << "\033[0m";
    std::cout.flush();
    return 0;
}

// ── Entry point ─────────────────────────────────────────────────────────
// On Windows the real entry point is wmain, so arguments arrive as UTF-16 and
// can be converted losslessly to the UTF-8 the rest of the program uses.  The
// narrow argv of main() is encoded in the active ANSI code page, which silently
// mangles any path or pattern containing characters that code page lacks.

#ifdef _WIN32
int wmain(int argc, wchar_t* wargv[]) {
    ConsoleCodePage cp;

    std::vector<std::string> args;
    args.reserve((size_t)argc);
    for (int i = 0; i < argc; ++i) args.push_back(wide_to_utf8(wargv[i]));

    std::vector<char*> argv;
    argv.reserve((size_t)argc + 1);
    for (auto& a : args) argv.push_back(a.data());
    argv.push_back(nullptr);

    return run(argc, argv.data());
}
#else
int main(int argc, char* argv[]) {
    return run(argc, argv);
}
#endif
