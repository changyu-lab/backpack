# CMake generated Testfile for 
# Source directory: C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/test/visualgaze
# Build directory: C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/build-gaze-blend
# 
# This file includes the relevant testing commands required for 
# testing this directory and lists subdirectories to be tested as well.
if("${CTEST_CONFIGURATION_TYPE}" MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
  add_test(visual_gaze_formulas "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/build-gaze-blend/Debug/visual_gaze_test.exe")
  set_tests_properties(visual_gaze_formulas PROPERTIES  _BACKTRACE_TRIPLES "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/test/visualgaze/CMakeLists.txt;7;add_test;C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/test/visualgaze/CMakeLists.txt;0;")
elseif("${CTEST_CONFIGURATION_TYPE}" MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
  add_test(visual_gaze_formulas "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/build-gaze-blend/Release/visual_gaze_test.exe")
  set_tests_properties(visual_gaze_formulas PROPERTIES  _BACKTRACE_TRIPLES "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/test/visualgaze/CMakeLists.txt;7;add_test;C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/test/visualgaze/CMakeLists.txt;0;")
elseif("${CTEST_CONFIGURATION_TYPE}" MATCHES "^([Mm][Ii][Nn][Ss][Ii][Zz][Ee][Rr][Ee][Ll])$")
  add_test(visual_gaze_formulas "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/build-gaze-blend/MinSizeRel/visual_gaze_test.exe")
  set_tests_properties(visual_gaze_formulas PROPERTIES  _BACKTRACE_TRIPLES "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/test/visualgaze/CMakeLists.txt;7;add_test;C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/test/visualgaze/CMakeLists.txt;0;")
elseif("${CTEST_CONFIGURATION_TYPE}" MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
  add_test(visual_gaze_formulas "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/build-gaze-blend/RelWithDebInfo/visual_gaze_test.exe")
  set_tests_properties(visual_gaze_formulas PROPERTIES  _BACKTRACE_TRIPLES "C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/test/visualgaze/CMakeLists.txt;7;add_test;C:/Users/hitxi/.codex/worktrees/gaze-sibrc-collab/vvenc-LFNST/test/visualgaze/CMakeLists.txt;0;")
else()
  add_test(visual_gaze_formulas NOT_AVAILABLE)
endif()
