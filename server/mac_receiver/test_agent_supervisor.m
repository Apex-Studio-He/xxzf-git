#import <Foundation/Foundation.h>
#import "AgentSupervisor.h"

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) return 2;
        NSString *pidPath = [NSString stringWithUTF8String:argv[1]];
        NSTask *child = [NSTask new];
        child.launchPath = @"/bin/sleep";
        child.arguments = @[@"30"];
        XXZFInstallAgentSignalHandlers();
        [child launch];
        NSString *pid = [NSString stringWithFormat:@"%d\n", child.processIdentifier];
        if (![pid writeToFile:pidPath atomically:YES
                     encoding:NSUTF8StringEncoding error:nil]) {
            [child terminate];
            return 3;
        }
        return XXZFWaitForAgentTask(child);
    }
}
