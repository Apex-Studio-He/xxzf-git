#import <Foundation/Foundation.h>
#import <UserNotifications/UserNotifications.h>

static inline UNAuthorizationOptions XXZFNotificationAuthorizationOptions(void) {
    return (UNAuthorizationOptionAlert |
            UNAuthorizationOptionSound |
            UNAuthorizationOptionBadge);
}

static inline UNNotificationInterruptionLevel XXZFNotificationInterruptionLevel(void)
    API_AVAILABLE(macos(12.0)) {
    return UNNotificationInterruptionLevelActive;
}
