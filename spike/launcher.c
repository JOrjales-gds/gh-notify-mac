// Embeds Python in the app's own process so the process has the bundle's identity.
// usage: launcher PYTHONHOME PYTHONPATH python-args...
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

typedef int (*py_bytes_main_t)(int, char **);

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s PYTHONHOME PYTHONPATH python-args...\n", argv[0]);
        return 2;
    }
    char lib[4096];
    snprintf(lib, sizeof lib, "%s/lib/libpython3.13.dylib", argv[1]);
    setenv("PYTHONHOME", argv[1], 1);
    setenv("PYTHONPATH", argv[2], 1);
    void *handle = dlopen(lib, RTLD_NOW | RTLD_GLOBAL);
    if (!handle) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return 1;
    }
    py_bytes_main_t py_main = (py_bytes_main_t)dlsym(handle, "Py_BytesMain");
    if (!py_main) {
        fprintf(stderr, "Py_BytesMain not found\n");
        return 1;
    }
    argv[2] = argv[0];  // argv[2] becomes the program name
    return py_main(argc - 2, argv + 2);
}
