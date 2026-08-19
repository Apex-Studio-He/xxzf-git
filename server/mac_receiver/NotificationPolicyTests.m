#import <Foundation/Foundation.h>
#import "NotificationPolicy.h"

int main(void) {
    @autoreleasepool {
        if (@available(macOS 12.0, *)) {
            UNAuthorizationOptions options = XXZFNotificationAuthorizationOptions();
            if (options != (UNAuthorizationOptionAlert |
                            UNAuthorizationOptionSound |
                            UNAuthorizationOptionBadge)) {
                NSLog(@"unexpected notification authorization options");
                return 1;
            }
            if (XXZFNotificationInterruptionLevel()
                    != UNNotificationInterruptionLevelActive) {
                NSLog(@"notification interruption level is not active");
                return 2;
            }
        }
        NSLog(@"Notification policy tests passed");
    }
    return 0;
}
