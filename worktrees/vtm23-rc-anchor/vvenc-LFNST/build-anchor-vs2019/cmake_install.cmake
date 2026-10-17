# Install script for directory: C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST

# Set the install prefix
if(NOT DEFINED CMAKE_INSTALL_PREFIX)
  set(CMAKE_INSTALL_PREFIX "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/install")
endif()
string(REGEX REPLACE "/$" "" CMAKE_INSTALL_PREFIX "${CMAKE_INSTALL_PREFIX}")

# Set the install configuration name.
if(NOT DEFINED CMAKE_INSTALL_CONFIG_NAME)
  if(BUILD_TYPE)
    string(REGEX REPLACE "^[^A-Za-z0-9_]+" ""
           CMAKE_INSTALL_CONFIG_NAME "${BUILD_TYPE}")
  else()
    set(CMAKE_INSTALL_CONFIG_NAME "Release")
  endif()
  message(STATUS "Install configuration: \"${CMAKE_INSTALL_CONFIG_NAME}\"")
endif()

# Set the component getting installed.
if(NOT CMAKE_INSTALL_COMPONENT)
  if(COMPONENT)
    message(STATUS "Install component: \"${COMPONENT}\"")
    set(CMAKE_INSTALL_COMPONENT "${COMPONENT}")
  else()
    set(CMAKE_INSTALL_COMPONENT)
  endif()
endif()

# Is this installation the result of a crosscompile?
if(NOT DEFINED CMAKE_CROSSCOMPILING)
  set(CMAKE_CROSSCOMPILING "FALSE")
endif()

if(NOT CMAKE_INSTALL_LOCAL_ONLY)
  # Include the install script for the subdirectory.
  include("C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/source/Lib/vvenc/cmake_install.cmake")
endif()

if(NOT CMAKE_INSTALL_LOCAL_ONLY)
  # Include the install script for the subdirectory.
  include("C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/source/App/vvencapp/cmake_install.cmake")
endif()

if(NOT CMAKE_INSTALL_LOCAL_ONLY)
  # Include the install script for the subdirectory.
  include("C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/source/App/vvencFFapp/cmake_install.cmake")
endif()

if(NOT CMAKE_INSTALL_LOCAL_ONLY)
  # Include the install script for the subdirectory.
  include("C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/test/vvenclibtest/cmake_install.cmake")
endif()

if(NOT CMAKE_INSTALL_LOCAL_ONLY)
  # Include the install script for the subdirectory.
  include("C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/test/vvencinterfacetest/cmake_install.cmake")
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include/vvenc" TYPE FILE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/vvenc/version.h")
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include" TYPE DIRECTORY FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/include/vvenc")
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/lib/release-static/vvenc.lib")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/bin" TYPE EXECUTABLE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/bin/release-static/vvencapp.exe")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/lib/debug-static/vvenc.lib")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/bin" TYPE EXECUTABLE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/bin/debug-static/vvencapp.exe")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/lib/relwithdebinfo-static/vvenc.lib")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/bin" TYPE EXECUTABLE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/bin/relwithdebinfo-static/vvencapp.exe")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/bin" TYPE FILE OPTIONAL FILES
      )
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/bin" TYPE FILE OPTIONAL FILES
      )
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE FILE OPTIONAL FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/lib/debug-static/vvenc.pdb")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE FILE OPTIONAL FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/lib/relwithdebinfo-static/vvenc.pdb")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/bin" TYPE FILE OPTIONAL FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/bin/debug-static/vvencapp.pdb")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/bin" TYPE FILE OPTIONAL FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/bin/relwithdebinfo-static/vvencapp.pdb")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc" TYPE FILE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/cmake/install/vvencConfig.cmake")
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc" TYPE FILE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/vvencConfigVersion.cmake")
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
    if(EXISTS "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc/vvencTargets-static.cmake")
      file(DIFFERENT EXPORT_FILE_CHANGED FILES
           "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc/vvencTargets-static.cmake"
           "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/CMakeFiles/Export/lib/cmake/vvenc/vvencTargets-static.cmake")
      if(EXPORT_FILE_CHANGED)
        file(GLOB OLD_CONFIG_FILES "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc/vvencTargets-static-*.cmake")
        if(OLD_CONFIG_FILES)
          message(STATUS "Old export file \"$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc/vvencTargets-static.cmake\" will be replaced.  Removing files [${OLD_CONFIG_FILES}].")
          file(REMOVE ${OLD_CONFIG_FILES})
        endif()
      endif()
    endif()
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc" TYPE FILE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/CMakeFiles/Export/lib/cmake/vvenc/vvencTargets-static.cmake")
  endif("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc" TYPE FILE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/CMakeFiles/Export/lib/cmake/vvenc/vvencTargets-static-release.cmake")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
    if(EXISTS "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc/vvencTargets-static.cmake")
      file(DIFFERENT EXPORT_FILE_CHANGED FILES
           "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc/vvencTargets-static.cmake"
           "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/CMakeFiles/Export/lib/cmake/vvenc/vvencTargets-static.cmake")
      if(EXPORT_FILE_CHANGED)
        file(GLOB OLD_CONFIG_FILES "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc/vvencTargets-static-*.cmake")
        if(OLD_CONFIG_FILES)
          message(STATUS "Old export file \"$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc/vvencTargets-static.cmake\" will be replaced.  Removing files [${OLD_CONFIG_FILES}].")
          file(REMOVE ${OLD_CONFIG_FILES})
        endif()
      endif()
    endif()
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc" TYPE FILE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/CMakeFiles/Export/lib/cmake/vvenc/vvencTargets-static.cmake")
  endif("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc" TYPE FILE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/CMakeFiles/Export/lib/cmake/vvenc/vvencTargets-static-debug.cmake")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
    if(EXISTS "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc/vvencTargets-static.cmake")
      file(DIFFERENT EXPORT_FILE_CHANGED FILES
           "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc/vvencTargets-static.cmake"
           "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/CMakeFiles/Export/lib/cmake/vvenc/vvencTargets-static.cmake")
      if(EXPORT_FILE_CHANGED)
        file(GLOB OLD_CONFIG_FILES "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc/vvencTargets-static-*.cmake")
        if(OLD_CONFIG_FILES)
          message(STATUS "Old export file \"$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc/vvencTargets-static.cmake\" will be replaced.  Removing files [${OLD_CONFIG_FILES}].")
          file(REMOVE ${OLD_CONFIG_FILES})
        endif()
      endif()
    endif()
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc" TYPE FILE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/CMakeFiles/Export/lib/cmake/vvenc/vvencTargets-static.cmake")
  endif("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
  if("${CMAKE_INSTALL_CONFIG_NAME}" MATCHES "^([Rr][Ee][Ll][Ww][Ii][Tt][Hh][Dd][Ee][Bb][Ii][Nn][Ff][Oo])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/cmake/vvenc" TYPE FILE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/CMakeFiles/Export/lib/cmake/vvenc/vvencTargets-static-relwithdebinfo.cmake")
  endif()
endif()

if("x${CMAKE_INSTALL_COMPONENT}x" STREQUAL "xUnspecifiedx" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/pkgconfig" TYPE FILE FILES "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/pkgconfig/libvvenc.pc")
endif()

if(CMAKE_INSTALL_COMPONENT)
  set(CMAKE_INSTALL_MANIFEST "install_manifest_${CMAKE_INSTALL_COMPONENT}.txt")
else()
  set(CMAKE_INSTALL_MANIFEST "install_manifest.txt")
endif()

string(REPLACE ";" "\n" CMAKE_INSTALL_MANIFEST_CONTENT
       "${CMAKE_INSTALL_MANIFEST_FILES}")
file(WRITE "C:/Users/hitxi/.codex/worktrees/vtm23-rc-anchor/vvenc-LFNST/build-anchor-vs2019/${CMAKE_INSTALL_MANIFEST}"
     "${CMAKE_INSTALL_MANIFEST_CONTENT}")
