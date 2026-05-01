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
#include <utility>
#include <vector>

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace fs = std::filesystem;

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
#endif

// ── Config file (simple INI) ────────────────────────────────────────────

struct IniFile {
    std::map<std::string, std::map<std::string, std::string>> sections;

    bool load(const std::string& path) {
        std::ifstream f(path);
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
        std::ofstream f(path);
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
    for (auto& c : fs::path(p))
        if (!c.empty()) parts.push_back(c.string());
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
"                           without -P, any match is shown. with -P, all\n"
"                           patterns must appear within the proximity window\n"
"  -P, --proximity NUM      all specified patterns must occur within NUM lines\n"
"                           of each other\n"
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
    if (!fs::exists(directory, ec)) {
        std::cout << g_c.err << "directory doesn't exist: "
                  << g_c.normal << directory << "\n";
        return {};
    }
    if (!fs::is_directory(directory, ec)) {
        std::cout << g_c.err << "is not a directory: "
                  << g_c.normal << directory << "\n";
        return {};
    }
    std::vector<std::string> entries;
    try {
        for (auto& de : fs::directory_iterator(directory)) {
            entries.push_back(de.path().filename().string());
        }
    } catch (const fs::filesystem_error&) {
        std::cout << g_c.err << "Permission denied: "
                  << g_c.normal << directory << "\n";
    }
    return entries;
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
        std::string p = (fs::path(directory) / fn).string();
        std::error_code ec;
        if (fs::is_regular_file(p, ec)) {   // follows symlinks (matches os.path.isfile)
            cb(p, fn);
        } else if (fs::is_directory(p, ec)) {
            PathParts parts2 = parts;
            parts2.push_back(fn);

            // With -r, skip symlinked directories unless explicitly in -p
            if (g_args.recursive && fs::is_symlink(fs::symlink_status(p, ec)) &&
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

    std::ifstream inf(path, std::ios::binary);
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
        if (g_args.negate) {
            bool any = false;
            for (auto& rc : g_regexes)
                if (std::regex_search(data, rc)) { any = true; break; }
            if (!any) prn_filename(path);
        } else if (g_args.filenames_only) {
            for (auto& rc : g_regexes)
                if (std::regex_search(data, rc)) { prn_filename(path); return; }
        } else {
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
            // OR mode
            bool found = false;
            while (std::getline(inf, line)) {
                if (g_interrupted) return;
                for (auto& rc : g_regexes) {
                    if (std::regex_search(line, rc)) { found = true; break; }
                }
                if (found) break;
            }
            if (found && g_args.filenames_only) prn_filename(path);
            if (!found && g_args.negate)        prn_filename(path);
        }
        return;
    }

    // ── full output mode ────────────────────────────────────────────
    int num_matches = 0;

    if (g_args.proximity >= 0) {
        // ── proximity mode ──────────────────────────────────────────
        int buf_size = g_args.proximity + g_before_ctx + 1;
        std::deque<std::pair<int, std::string>> prox_buf;
        std::map<int, int> last_match;
        int last_printed_line = 0;
        int after_remaining = 0;
        bool matched_one = false;

        while (std::getline(inf, line)) {
            if (g_interrupted) return;
            ++line_number;
            prox_buf.push_back({line_number, line});
            if ((int)prox_buf.size() > buf_size)
                prox_buf.pop_front();

            for (int idx = 0; idx < (int)g_regexes.size(); ++idx)
                if (std::regex_search(line, g_regexes[idx]))
                    last_match[idx] = line_number;

            // expire
            for (auto it = last_match.begin(); it != last_match.end(); )
                it = (line_number - it->second >= g_args.proximity)
                         ? last_match.erase(it) : std::next(it);

            // after-context from a previous proximity match
            if (after_remaining > 0 && line_number > last_printed_line) {
                prn(path, line_number, line);
                last_printed_line = line_number;
                --after_remaining;
            }
            // proximity match
            else if ((int)last_match.size() == (int)g_regexes.size()) {
                ++num_matches;
                if (g_args.max_count >= 0 && num_matches > g_args.max_count)
                    break;
                int min_ln = last_match.begin()->second;
                int max_ln = min_ln;
                for (auto& [_, ln] : last_match) {
                    min_ln = std::min(min_ln, ln);
                    max_ln = std::max(max_ln, ln);
                }
                int start_ln = std::max(min_ln - g_before_ctx,
                                        last_printed_line + 1);
                if (matched_one && start_ln > last_printed_line + 1)
                    std::cout << "-----\n";
                for (auto& [bln, bline] : prox_buf) {
                    if (bln >= start_ln && bln <= max_ln &&
                        bln > last_printed_line) {
                        prn(path, bln, bline);
                    }
                }
                last_printed_line = std::max(last_printed_line, max_ln);
                matched_one = true;
                after_remaining = g_after_ctx;
                last_match.clear();
            }
        }
    } else {
        // ── normal (OR) mode ────────────────────────────────────────
        if (g_before_ctx || g_after_ctx) {
            // Context-aware search
            std::deque<std::pair<int, std::string>> before_buf;
            int last_printed_line = 0;
            int after_remaining   = 0;
            bool matched_one      = false;

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
                    if (matched_one && start > last_printed_line + 1)
                        std::cout << "-----\n";

                    // Print before-context lines not yet printed
                    for (auto& [bln, bline] : before_buf) {
                        if (bln >= start && bln > last_printed_line) {
                            prn(path, bln, bline);
                            last_printed_line = bln;
                        }
                    }
                    // Print the match line itself
                    if (line_number > last_printed_line) {
                        prn(path, line_number, line);
                        last_printed_line = line_number;
                    }
                    after_remaining = g_after_ctx;
                    matched_one = true;
                } else if (after_remaining > 0) {
                    prn(path, line_number, line);
                    last_printed_line = line_number;
                    --after_remaining;
                }

                // Maintain before-context buffer
                before_buf.push_back({line_number, line});
                if ((int)before_buf.size() > g_before_ctx)
                    before_buf.pop_front();
            }
        } else {
            // Simple (no context)
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
                    prn(path, line_number, line);
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  main
// ═══════════════════════════════════════════════════════════════════════

int main(int argc, char* argv[]) {
    std::signal(SIGINT, sigint_handler);

    if (argc == 1) { print_help(); return 0; }

    parse_args(argc, argv, g_args);

    // ── Resolve config-file path (same directory as executable) ─────
    std::string config_path;
    {
#ifdef _WIN32
        char exe[MAX_PATH]{};
        GetModuleFileNameA(nullptr, exe, MAX_PATH);
        config_path = (fs::path(exe).parent_path() / "grep.colors.conf").string();
#else
        std::error_code ec;
        auto exepath = fs::read_symlink("/proc/self/exe", ec);
        if (ec) exepath = fs::absolute(argv[0], ec);
        config_path = (exepath.parent_path() / "grep.colors.conf").string();
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

    for (auto& pat : all_patterns) {
        std::string effective = g_args.dotall ? make_dotall_pattern(pat) : pat;
        try {
            g_regexes.emplace_back(effective, flags);
        } catch (const std::regex_error& e) {
            std::cout << g_c.err << "Regex pattern error in '" << pat << "': "
                      << g_c.normal << e.what() << "\n";
            return 1;
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
        bool was_absolute_path = false;
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
                        was_absolute_path = true;
                    }
                } else {
                    i_files2.push_back(spec);
                }
            }
            if (!was_absolute_path && i_files2.empty())
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
                            std::string fp = (fs::path(dir) / fn).string();
                            std::error_code ec;
                            if (!fs::is_directory(fp, ec) &&
                                fnmatch_match(spec, fn, g_case_sensitive_fn) &&
                                !excluded_file(fn))
                                process(fp);
                        }
                    }
                } else {
                    i_files2.push_back(spec);
                }
            }
            if (i_files2.empty()) i_files2.push_back("*");

            for (auto& ip : g_i_paths) {
                if (g_interrupted) break;
                for (auto& fn : ld(ip)) {
                    std::string fp = (fs::path(ip) / fn).string();
                    std::error_code ec;
                    if (!fs::is_directory(fp, ec) &&
                        match_file(fn, i_files2) && !excluded_file(fn))
                        process(fp);
                }
            }
        }

        if (g_processed.empty() && !g_interrupted)
            std::cout << "No files matched your criteria.\n";

    } catch (...) {
        // Catch-all (unlikely in practice)
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
