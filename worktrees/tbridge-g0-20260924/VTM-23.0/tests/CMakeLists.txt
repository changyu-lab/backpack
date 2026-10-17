add_executable( rc360_uprop_core_test rc360_uprop_core_test.cpp )
target_include_directories( rc360_uprop_core_test PRIVATE ${CMAKE_SOURCE_DIR} )
target_link_libraries( rc360_uprop_core_test EncoderLib CommonLib )
set_target_properties( rc360_uprop_core_test PROPERTIES FOLDER test )

add_executable( rc360_paper_ti_core_test rc360_paper_ti_core_test.cpp )
target_include_directories( rc360_paper_ti_core_test PRIVATE ${CMAKE_SOURCE_DIR} )
target_link_libraries( rc360_paper_ti_core_test EncoderLib CommonLib )
set_target_properties( rc360_paper_ti_core_test PROPERTIES FOLDER test )

add_executable( rc360_oracle_replay_core_test rc360_oracle_replay_core_test.cpp )
target_include_directories( rc360_oracle_replay_core_test PRIVATE ${CMAKE_SOURCE_DIR} )
target_link_libraries( rc360_oracle_replay_core_test EncoderLib CommonLib )
set_target_properties( rc360_oracle_replay_core_test PROPERTIES FOLDER test )
