#import <Cocoa/Cocoa.h>
#import <UserNotifications/UserNotifications.h>

@interface XXZFNotificationDelegate : NSObject
    <UNUserNotificationCenterDelegate, NSUserNotificationCenterDelegate>
@end

@implementation XXZFNotificationDelegate
- (void)userNotificationCenter:(UNUserNotificationCenter *)center
       willPresentNotification:(UNNotification *)notification
         withCompletionHandler:(void (^)(UNNotificationPresentationOptions options))completionHandler {
    UNNotificationPresentationOptions options = UNNotificationPresentationOptionSound;
    if (@available(macOS 11.0, *)) {
        options |= UNNotificationPresentationOptionBanner | UNNotificationPresentationOptionList;
    } else {
        options |= UNNotificationPresentationOptionAlert;
    }
    completionHandler(options);
}

- (BOOL)userNotificationCenter:(NSUserNotificationCenter *)center
        shouldPresentNotification:(NSUserNotification *)notification {
    return YES;
}
@end

static BOOL RunLoopUntil(BOOL (^condition)(void), NSTimeInterval timeout) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:timeout];
    while (!condition() && [deadline timeIntervalSinceNow] > 0) {
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                 beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
    }
    return condition();
}

static void RunLoopFor(NSTimeInterval seconds) {
    RunLoopUntil(^BOOL{
        return NO;
    }, seconds);
}

static int DeliverModernNotification(NSString *title, NSString *body,
                                     XXZFNotificationDelegate *delegate) {
    UNUserNotificationCenter *center = [UNUserNotificationCenter currentNotificationCenter];
    center.delegate = delegate;

    __block BOOL authorizationFinished = NO;
    __block BOOL authorized = NO;
    __block NSError *authorizationError = nil;
    UNAuthorizationOptions options =
            UNAuthorizationOptionAlert | UNAuthorizationOptionSound | UNAuthorizationOptionBadge;
    [center requestAuthorizationWithOptions:options
                          completionHandler:^(BOOL granted, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            authorized = granted;
            authorizationError = error;
            authorizationFinished = YES;
        });
    }];

    if (!RunLoopUntil(^BOOL{
        return authorizationFinished;
    }, 8.0)) {
        fprintf(stderr, "notification authorization timed out\n");
        return 2;
    }
    if (!authorized) {
        fprintf(stderr, "notification authorization denied: %s\n",
                authorizationError.localizedDescription.UTF8String ?: "unknown error");
        return 3;
    }

    UNMutableNotificationContent *content = [UNMutableNotificationContent new];
    content.title = title ?: @"讯桥";
    content.body = body ?: @"";
    content.sound = [UNNotificationSound defaultSound];
    if (@available(macOS 12.0, *)) {
        content.interruptionLevel = UNNotificationInterruptionLevelActive;
    }

    NSString *identifier = [NSString stringWithFormat:@"xxzf-%@", NSUUID.UUID.UUIDString];
    UNNotificationRequest *request =
            [UNNotificationRequest requestWithIdentifier:identifier content:content trigger:nil];
    __block BOOL deliveryFinished = NO;
    __block NSError *deliveryError = nil;
    [center addNotificationRequest:request withCompletionHandler:^(NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            deliveryError = error;
            deliveryFinished = YES;
        });
    }];

    if (!RunLoopUntil(^BOOL{
        return deliveryFinished;
    }, 5.0)) {
        fprintf(stderr, "notification delivery timed out\n");
        return 4;
    }
    if (deliveryError) {
        fprintf(stderr, "notification delivery failed: %s\n",
                deliveryError.localizedDescription.UTF8String ?: "unknown error");
        return 5;
    }

    RunLoopFor(2.0);
    return 0;
}

static int DeliverLegacyNotification(NSString *title, NSString *body,
                                     XXZFNotificationDelegate *delegate) {
    NSUserNotificationCenter *center = [NSUserNotificationCenter defaultUserNotificationCenter];
    center.delegate = delegate;

    NSUserNotification *notification = [NSUserNotification new];
    notification.title = title ?: @"讯桥";
    notification.informativeText = body ?: @"";
    notification.soundName = NSUserNotificationDefaultSoundName;
    [center deliverNotification:notification];
    RunLoopFor(2.0);
    return 0;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        [app finishLaunching];

        NSString *firstArgument = argc > 1
                ? [NSString stringWithUTF8String:argv[1]]
                : @"";
        if ([firstArgument isEqualToString:@"--clear"]) {
            UNUserNotificationCenter *center = [UNUserNotificationCenter currentNotificationCenter];
            [center removeAllPendingNotificationRequests];
            [center removeAllDeliveredNotifications];
            [[NSUserNotificationCenter defaultUserNotificationCenter]
                    removeAllDeliveredNotifications];
            RunLoopFor(0.3);
            return 0;
        }

        BOOL useLegacyDelivery = [firstArgument isEqualToString:@"--legacy"];
        int argumentOffset = useLegacyDelivery ? 2 : 1;
        NSString *title = argc > argumentOffset
                ? [NSString stringWithUTF8String:argv[argumentOffset]]
                : @"讯桥";
        NSString *body = argc > argumentOffset + 1
                ? [NSString stringWithUTF8String:argv[argumentOffset + 1]]
                : @"收到一条安卓通知";
        XXZFNotificationDelegate *delegate = [XXZFNotificationDelegate new];

        if (useLegacyDelivery) {
            return DeliverLegacyNotification(title, body, delegate);
        }
        if (@available(macOS 10.14, *)) {
            return DeliverModernNotification(title, body, delegate);
        }
        return DeliverLegacyNotification(title, body, delegate);
    }
}
