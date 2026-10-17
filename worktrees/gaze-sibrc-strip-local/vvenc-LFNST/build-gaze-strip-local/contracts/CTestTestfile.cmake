# CMake generated Testfile for 
# Source directory: C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/test/striplocal
# Build directory: C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/build-gaze-strip-local/contracts
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
if("${CTEST_CONFIGURATION_TYPE}" MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
  add_test(strip_local_contract "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/build-gaze-strip-local/contracts/Debug/strip_local_test.exe")
  set_tests_properties(strip_local_contract PROPERTIES  _BACKTRACE_TRIPLES "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/test/striplocal/CMakeLists.txt;7;add_test;C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/test/striplocal/CMakeLists.txt;0;")
elseif("${CTEST_CONFIGURATION_TYPE}" MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
  add_test(strip_local_contract "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/build-gaze-strip-local/contracts/Release/strip_local_test.exe")
  set_tests_properties(strip_local_contract PROPERTIES  _BACKTRACE_TRIPLES "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/test/striplocal/CMakeLists.txt;7;add_test;C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/test/striplocal/CMakeLists.txt;0;")
elseif("${CTEST_CONFIGURATION_TYPE}" MATCHES "^([Mm][Ii][Nn][Ss][Ii][Zz][Ee][Rr][Ee][Ll])$")
  add_test(strip_local_contract "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/build-gaze-strip-local/contracts/MinSizeRel/strip_local_test.exe")
  set_tests_properties(strip_local_contract PROPERTIES  _BACKTRACE_TRIPLES "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/test/striplocal/CMakeLists.txt;7;add_test;C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/test/striplocal/CMakeLists.txt;0;")
elseif("${CTEST_CONFIGURATION_TYPE}" MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
  add_test(strip_local_contract "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/build-gaze-strip-local/contracts/RelWithDebInfo/strip_local_test.exe")
  set_tests_properties(strip_local_contract PROPERTIES  _BACKTRACE_TRIPLES "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/test/striplocal/CMakeLists.txt;7;add_test;C:/Users/hitxi/.codex/worktrees/gaze-sibrc-strip-local/vvenc-LFNST/test/striplocal/CMakeLists.txt;0;")
else()
  add_test(strip_local_contract NOT_AVAILABLE)
endif()
