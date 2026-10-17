#----------------------------------------------------------------
# Generated CMake target import file for configuration "RelWithDebInfo".
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "vvenc::vvenc" for configuration "RelWithDebInfo"
set_property(TARGET vvenc::vvenc APPEND PROPERTY IMPORTED_CONFIGURATIONS RELWITHDEBINFO)
set_target_properties(vvenc::vvenc PROPERTIES
  IMPORTED_LINK_INTERFACE_LANGUAGES_RELWITHDEBINFO "CXX;RC"
  IMPORTED_LOCATION_RELWITHDEBINFO "${_IMPORT_PREFIX}/lib/vvenc.lib"
  )

list(APPEND _IMPORT_CHECK_TARGETS vvenc::vvenc )
list(APPEND _IMPORT_CHECK_FILES_FOR_vvenc::vvenc "${_IMPORT_PREFIX}/lib/vvenc.lib" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
