# C/CMake, PlatformIO, Rust, Go idioms

| Stack | Current | Legacy — reject |
|---|---|---|
| C (the build's `-std`) + CMake ≥ 3.20 | `target_sources`/`target_link_libraries`/`target_compile_options`, `target_compile_features(<tgt> PRIVATE c_std_<the build's std>)` | `include_directories`, `add_definitions`, global `CMAKE_C_FLAGS` edits |
| PlatformIO | envs in `platformio.ini` (`[env:<name>]`, `build_flags`, `lib_deps`) | hand-rolled Makefiles, hardcoded toolchain paths |
| Rust 2021/2024 | `let ... else`, let chains (edition 2024 only), `?`, `thiserror`/`anyhow` per crate convention | nested `match` for early return, `unwrap()` in library code, `extern crate` |
| Go 1.22+ | `for i := range n`, per-iteration loop variables, `errors.Is/As`, `slices`/`maps` | `for i := 0; i < n; i++` where range fits, loop-variable capture workarounds, `interface{}` |
