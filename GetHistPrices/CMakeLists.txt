cmake_minimum_required (VERSION 3.9)

set (PROJECT GetHistPrices)

project (${PROJECT})

set (CMAKE_EXPORT_COMPILE_COMMANDS ON)
set (CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -pthread -DINCLUDE_PLATFORM")

set (3RD_PARTY "${PROJECT_SOURCE_DIR}/3rd_party")
set (SAMPLE_TOOLS_DIR "${3RD_PARTY}/sample_tools")
set (FOREXCONNECT_DIR "${3RD_PARTY}/ForexConnect")

include_directories (${FOREXCONNECT_DIR}/include
                     ${SAMPLE_TOOLS_DIR}/include
                     ${3RD_PARTY}/json/include/
                     ${3RD_PARTY}/cpp-httplib-master
                    )

link_directories (${FOREXCONNECT_DIR}/lib
                  ${SAMPLE_TOOLS_DIR}/lib)

set (HEADERS
    src/stdafx.h
    src/CommonSources.h
    src/LoginParams.h
    src/ResponseListener.h
    src/SampleParams.h
    src/SessionStatusListener.h
    )

set (SOURCES
    src/main.cpp
    src/CommonSources.cpp
    src/LoginParams.cpp
    src/ResponseListener.cpp
    src/SampleParams.cpp
    src/SessionStatusListener.cpp
    )

if (NOT CMAKE_CROSSCOMPILING)
    add_executable (${PROJECT} ${HEADERS} ${SOURCES})
else ()
    add_library (${PROJECT} STATIC ${HEADERS} ${SOURCES})
endif ()

target_link_libraries (${PROJECT} ForexConnect sample_tools)

if (${CMAKE_SYSTEM} MATCHES "Linux")
    set_target_properties (${PROJECT} PROPERTIES
          LINK_FLAGS "-Wl,-rpath,\$ORIGIN"
    )
    set (SHAREDSUFFIX "so")
elseif (${CMAKE_SYSTEM} MATCHES "Darwin")
    set_target_properties (${PROJECT} PROPERTIES
          BUILD_WITH_INSTALL_RPATH 1
          INSTALL_NAME_DIR "@rpath"
          LINK_FLAGS "-Wl,-rpath,@loader_path,-rpath,./"
    )
    set (SHAREDSUFFIX "dylib")
endif ()

# Post - build event to create symlinks for shared objects
add_custom_command (TARGET ${PROJECT}
    POST_BUILD
    COMMAND find ${FOREXCONNECT_DIR}/lib/ -name lib*.${SHAREDSUFFIX} -exec ln -sf {} \;
    COMMAND find ${SAMPLE_TOOLS_DIR}/lib/ -name lib*.${SHAREDSUFFIX} -exec ln -sf {} \;
    COMMAND cp ${PROJECT_SOURCE_DIR}/GetHistPrices.cfg .;

    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}
    VERBATIM
)
