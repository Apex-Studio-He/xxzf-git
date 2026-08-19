#import <Foundation/Foundation.h>
#include <signal.h>
#include <unistd.h>

static volatile sig_atomic_t XXZFAgentStopRequested = 0;

static void XXZFAgentRequestStop(int signalNumber) {
    (void)signalNumber;
    XXZFAgentStopRequested = 1;
}

static inline void XXZFInstallAgentSignalHandlers(void) {
    XXZFAgentStopRequested = 0;
    struct sigaction action = {0};
    action.sa_handler = XXZFAgentRequestStop;
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGHUP, &action, NULL);
}

static inline int XXZFWaitForAgentTask(NSTask *task) {
    while (task.isRunning && !XXZFAgentStopRequested) {
        usleep(50000);
    }
    if (XXZFAgentStopRequested && task.isRunning) {
        [task terminate];
        for (NSUInteger attempt = 0; attempt < 40 && task.isRunning; attempt++) {
            usleep(50000);
        }
        if (task.isRunning) kill(task.processIdentifier, SIGKILL);
    }
    [task waitUntilExit];
    return XXZFAgentStopRequested ? 0 : task.terminationStatus;
}
