#import <Cocoa/Cocoa.h>
#import <CoreImage/CoreImage.h>
#import <Security/Security.h>
#import <SystemConfiguration/SystemConfiguration.h>
#import <UserNotifications/UserNotifications.h>
#import "AgentSupervisor.h"
#import "NotificationPolicy.h"
#import "UpdateManager.h"
#include <netinet/in.h>
#include <sys/stat.h>
#include <unistd.h>

static NSString *const XXZFPublicBase = @"https://example.com/xxzf";
static NSString *const XXZFKeychainService = @"com.zundu.xxzf.notifier.receiver";
static NSString *const XXZFKeychainAccount = @"receiver-secret";

static NSDictionary *XXZFKeychainQuery(void) {
    return @{
        (__bridge id)kSecClass: (__bridge id)kSecClassGenericPassword,
        (__bridge id)kSecAttrService: XXZFKeychainService,
        (__bridge id)kSecAttrAccount: XXZFKeychainAccount
    };
}

static BOOL XXZFStoreReceiverSecret(NSString *secret) {
    if (!secret.length) return NO;
    NSData *value = [secret dataUsingEncoding:NSUTF8StringEncoding];
    if (!value.length) return NO;
    NSDictionary *query = XXZFKeychainQuery();
    OSStatus status = SecItemUpdate((__bridge CFDictionaryRef)query,
                                    (__bridge CFDictionaryRef)@{
        (__bridge id)kSecValueData: value,
        (__bridge id)kSecAttrAccessible:
            (__bridge id)kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
    });
    if (status == errSecItemNotFound) {
        NSMutableDictionary *item = [query mutableCopy];
        item[(__bridge id)kSecValueData] = value;
        item[(__bridge id)kSecAttrAccessible] =
            (__bridge id)kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly;
        status = SecItemAdd((__bridge CFDictionaryRef)item, NULL);
    }
    return status == errSecSuccess;
}

static NSString *XXZFCopyReceiverSecret(void) {
    NSMutableDictionary *query = [XXZFKeychainQuery() mutableCopy];
    query[(__bridge id)kSecReturnData] = @YES;
    query[(__bridge id)kSecMatchLimit] = (__bridge id)kSecMatchLimitOne;
    CFTypeRef result = NULL;
    OSStatus status = SecItemCopyMatching((__bridge CFDictionaryRef)query, &result);
    if (status != errSecSuccess || !result) return nil;
    NSData *data = CFBridgingRelease(result);
    NSString *secret = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    return secret.length ? secret : nil;
}

static BOOL XXZFDeleteReceiverSecret(void) {
    OSStatus status = SecItemDelete((__bridge CFDictionaryRef)XXZFKeychainQuery());
    return status == errSecSuccess || status == errSecItemNotFound;
}

static NSString *XXZFSupportDirectory(void) {
    return [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/XXZF"];
}

static int XXZFRunBackgroundAgent(void) {
    NSString *credentialPath = [XXZFSupportDirectory() stringByAppendingPathComponent:@"receiver.json"];
    NSData *data = [NSData dataWithContentsOfFile:credentialPath];
    NSDictionary *config = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    NSString *receiverId = [config[@"receiverId"] isKindOfClass:NSString.class]
        ? config[@"receiverId"] : @"";
    NSString *secret = XXZFCopyReceiverSecret();
    if (!receiverId.length || !secret.length) return 2;

    NSString *runner = [XXZFSupportDirectory() stringByAppendingPathComponent:@"mac_client.py"];
    if (![NSFileManager.defaultManager isExecutableFileAtPath:@"/usr/bin/python3"]
            || ![NSFileManager.defaultManager fileExistsAtPath:runner]) return 3;

    NSMutableDictionary *credential = [config mutableCopy] ?: [NSMutableDictionary dictionary];
    credential[@"receiverId"] = receiverId;
    credential[@"receiverSecret"] = secret;
    [credential removeObjectForKey:@"servers"];
    NSData *credentialData = [NSJSONSerialization dataWithJSONObject:credential options:0 error:nil];
    if (!credentialData.length) return 4;

    NSPipe *input = [NSPipe pipe];
    NSTask *task = [NSTask new];
    task.launchPath = @"/usr/bin/python3";
    task.arguments = @[runner, @"--credentials-stdin"];
    task.currentDirectoryPath = XXZFSupportDirectory();
    task.standardInput = input;
    task.standardOutput = NSFileHandle.fileHandleWithStandardOutput;
    task.standardError = NSFileHandle.fileHandleWithStandardError;
    @try {
        XXZFInstallAgentSignalHandlers();
        [task launch];
        [input.fileHandleForWriting writeData:credentialData];
        [input.fileHandleForWriting closeFile];
        return XXZFWaitForAgentTask(task);
    } @catch (__unused NSException *exception) {
        return 5;
    }
}

static BOOL HasNetworkConnection(void) {
    struct sockaddr_in zeroAddress;
    bzero(&zeroAddress, sizeof(zeroAddress));
    zeroAddress.sin_len = sizeof(zeroAddress);
    zeroAddress.sin_family = AF_INET;
    SCNetworkReachabilityRef reachability = SCNetworkReachabilityCreateWithAddress(
        NULL, (const struct sockaddr *)&zeroAddress);
    if (!reachability) return NO;
    SCNetworkReachabilityFlags flags = 0;
    BOOL read = SCNetworkReachabilityGetFlags(reachability, &flags);
    CFRelease(reachability);
    return read && (flags & kSCNetworkReachabilityFlagsReachable)
        && !(flags & kSCNetworkReachabilityFlagsConnectionRequired);
}

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

@interface XXZFNoRedirectDelegate : NSObject <NSURLSessionTaskDelegate>
@end

@implementation XXZFNoRedirectDelegate
- (void)URLSession:(NSURLSession *)session
              task:(NSURLSessionTask *)task
willPerformHTTPRedirection:(NSHTTPURLResponse *)response
        newRequest:(NSURLRequest *)request
 completionHandler:(void (^)(NSURLRequest * _Nullable))completionHandler {
    completionHandler(nil);
}
@end

static NSURLSession *XXZFHTTPSession(void) {
    static NSURLSession *session;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        NSURLSessionConfiguration *configuration = NSURLSessionConfiguration.ephemeralSessionConfiguration;
        configuration.URLCache = nil;
        configuration.requestCachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
        session = [NSURLSession sessionWithConfiguration:configuration
                                                delegate:[XXZFNoRedirectDelegate new]
                                           delegateQueue:nil];
    });
    return session;
}

static BOOL RunLoopUntil(BOOL (^condition)(void), NSTimeInterval timeout) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:timeout];
    while (!condition() && [deadline timeIntervalSinceNow] > 0) {
        [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode
                              beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
    }
    return condition();
}

static void RunLoopFor(NSTimeInterval seconds) {
    RunLoopUntil(^BOOL{ return NO; }, seconds);
}

static int DeliverNotification(NSString *title, NSString *body,
                               XXZFNotificationDelegate *delegate) {
    if (@available(macOS 13.0, *)) {
        UNUserNotificationCenter *center = UNUserNotificationCenter.currentNotificationCenter;
        center.delegate = delegate;
        __block BOOL authorizationFinished = NO;
        __block BOOL authorized = NO;
        [center requestAuthorizationWithOptions:XXZFNotificationAuthorizationOptions()
                                  completionHandler:^(BOOL granted, NSError *error) {
            (void)error;
            dispatch_async(dispatch_get_main_queue(), ^{
                authorized = granted;
                authorizationFinished = YES;
            });
        }];
        if (!RunLoopUntil(^BOOL{ return authorizationFinished; }, 8.0) || !authorized) return 2;

        UNMutableNotificationContent *content = [UNMutableNotificationContent new];
        content.title = title ?: @"转发";
        content.body = body ?: @"";
        content.sound = UNNotificationSound.defaultSound;
        if (@available(macOS 12.0, *)) {
            content.interruptionLevel = XXZFNotificationInterruptionLevel();
        }
        UNNotificationRequest *request = [UNNotificationRequest
            requestWithIdentifier:[NSString stringWithFormat:@"xxzf-%@", NSUUID.UUID.UUIDString]
                          content:content
                          trigger:nil];
        __block BOOL deliveryFinished = NO;
        __block NSError *deliveryError = nil;
        [center addNotificationRequest:request withCompletionHandler:^(NSError *error) {
            dispatch_async(dispatch_get_main_queue(), ^{
                deliveryError = error;
                deliveryFinished = YES;
            });
        }];
        if (!RunLoopUntil(^BOOL{ return deliveryFinished; }, 5.0) || deliveryError) return 3;
        RunLoopFor(1.5);
        return 0;
    }

    if (@available(macOS 10.14, *)) {
        __block BOOL authorizationFinished = NO;
        __block BOOL authorized = NO;
        [UNUserNotificationCenter.currentNotificationCenter
            requestAuthorizationWithOptions:XXZFNotificationAuthorizationOptions()
            completionHandler:^(BOOL granted, NSError *error) {
                (void)error;
                dispatch_async(dispatch_get_main_queue(), ^{
                    authorized = granted;
                    authorizationFinished = YES;
                });
            }];
        if (!RunLoopUntil(^BOOL{ return authorizationFinished; }, 8.0) || !authorized) return 2;
    }

    NSUserNotificationCenter *center = NSUserNotificationCenter.defaultUserNotificationCenter;
    center.delegate = delegate;
    NSUserNotification *notification = [NSUserNotification new];
    notification.title = title ?: @"转发";
    notification.informativeText = body ?: @"";
    notification.soundName = NSUserNotificationDefaultSoundName;
    [center deliverNotification:notification];
    RunLoopFor(1.5);
    return 0;
}

@interface ReceiverDelegate : NSObject <NSApplicationDelegate, UNUserNotificationCenterDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) NSTextField *statusLabel;
@property(nonatomic, strong) NSTextField *serverStatusLabel;
@property(nonatomic, strong) NSTextField *codeLabel;
@property(nonatomic, strong) NSTextField *expiryLabel;
@property(nonatomic, strong) NSImageView *qrView;
@property(nonatomic, strong) NSButton *pairButton;
@property(nonatomic, strong) NSButton *diagnosticButton;
@property(nonatomic, strong) NSTextField *diagnosticResultLabel;
@property(nonatomic, strong) NSButton *updateButton;
@property(nonatomic, strong) NSTextField *updateStatusLabel;
@property(nonatomic, strong) NSSegmentedControl *contentModeControl;
@property(nonatomic, strong) NSTimer *timer;
@property(nonatomic, strong) NSTimer *serverTimer;
@property(nonatomic, strong) NSTimer *updateTimer;
@property(nonatomic, strong) XXZFUpdateManager *updateManager;
@property(nonatomic, copy) NSString *receiverId;
@property(nonatomic, copy) NSString *receiverSecret;
@property(nonatomic, copy) NSString *receiverFingerprint;
@property(nonatomic) long long expiresAt;
@property(nonatomic, copy) NSString *pairingId;
@property(nonatomic, copy) NSString *contentMode;
@property(nonatomic) BOOL pairingSuccessShown;
@property(nonatomic) BOOL credentialRecoveryRequired;
@property(nonatomic, copy) NSString *serverStatusCode;
- (void)confirmCredentialRecovery;
- (BOOL)clearCredentialForRecovery;
- (BOOL)saveCredential;
@end

@implementation ReceiverDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    self.contentMode = @"full";
    if (@available(macOS 10.14, *)) {
        UNUserNotificationCenter.currentNotificationCenter.delegate = self;
        [UNUserNotificationCenter.currentNotificationCenter
            requestAuthorizationWithOptions:XXZFNotificationAuthorizationOptions()
            completionHandler:^(BOOL granted, NSError *error) {
                (void)granted;
                (void)error;
            }];
    }
    [self buildWindow];
    NSDictionary *info = NSBundle.mainBundle.infoDictionary;
    __weak typeof(self) weakSelf = self;
    self.updateManager = [[XXZFUpdateManager alloc]
        initWithOwnerWindow:self.window
         currentVersionCode:[info[@"CFBundleVersion"] integerValue]
             currentVersion:info[@"CFBundleShortVersionString"] ?: @"1.3.4"
              statusHandler:^(NSString *status, BOOL isError) {
        weakSelf.updateStatusLabel.stringValue = status ?: @"";
        weakSelf.updateStatusLabel.textColor = isError
            ? NSColor.systemRedColor : NSColor.secondaryLabelColor;
        weakSelf.updateButton.enabled = ![status isEqualToString:@"正在检查更新"];
    }];
    [self loadCredential];
    [self installRuntime];
    [self refreshServerStatus:nil];
    self.serverTimer = [NSTimer scheduledTimerWithTimeInterval:15
                                                       target:self
                                                     selector:@selector(refreshServerStatus:)
                                                     userInfo:nil
                                                      repeats:YES];
    [self performSelector:@selector(runStartupUpdateCheck) withObject:nil afterDelay:3.0];
    self.updateTimer = [NSTimer scheduledTimerWithTimeInterval:6 * 60 * 60
                                                        target:self
                                                      selector:@selector(runBackgroundUpdateCheck:)
                                                      userInfo:nil
                                                       repeats:YES];
    [NSApp activateIgnoringOtherApps:YES];
    [self.window makeKeyAndOrderFront:nil];
}

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

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    return NO;
}

- (NSTextField *)label:(NSString *)value size:(CGFloat)size weight:(NSFontWeight)weight {
    NSTextField *label = [NSTextField labelWithString:value];
    label.font = [NSFont systemFontOfSize:size weight:weight];
    label.textColor = NSColor.labelColor;
    label.alignment = NSTextAlignmentCenter;
    label.lineBreakMode = NSLineBreakByTruncatingTail;
    return label;
}

- (void)buildWindow {
    NSRect frame = NSMakeRect(0, 0, 440, 780);
    self.window = [[NSWindow alloc] initWithContentRect:frame
                                             styleMask:(NSWindowStyleMaskTitled |
                                                        NSWindowStyleMaskClosable |
                                                        NSWindowStyleMaskMiniaturizable)
                                               backing:NSBackingStoreBuffered
                                                 defer:NO];
    self.window.title = @"转发";
    self.window.releasedWhenClosed = NO;
    [self.window center];

    NSView *content = self.window.contentView;
    NSTextField *title = [self label:@"转发" size:27 weight:NSFontWeightBold];
    title.frame = NSMakeRect(24, 720, 392, 38);
    [content addSubview:title];

    NSTextField *role = [self label:@"接收设备 · 接收通知" size:13 weight:NSFontWeightMedium];
    role.textColor = NSColor.secondaryLabelColor;
    role.frame = NSMakeRect(24, 694, 392, 22);
    [content addSubview:role];

    self.serverStatusLabel = [self label:@"正在检查服务器" size:13 weight:NSFontWeightMedium];
    self.serverStatusLabel.textColor = NSColor.secondaryLabelColor;
    self.serverStatusLabel.frame = NSMakeRect(24, 666, 392, 22);
    [content addSubview:self.serverStatusLabel];

    self.statusLabel = [self label:@"未连接 · 请生成配对码" size:14 weight:NSFontWeightRegular];
    self.statusLabel.textColor = NSColor.secondaryLabelColor;
    self.statusLabel.frame = NSMakeRect(24, 638, 392, 24);
    [content addSubview:self.statusLabel];

    self.qrView = [[NSImageView alloc] initWithFrame:NSMakeRect(110, 408, 220, 220)];
    self.qrView.imageScaling = NSImageScaleProportionallyUpOrDown;
    self.qrView.wantsLayer = YES;
    self.qrView.layer.backgroundColor = NSColor.clearColor.CGColor;
    self.qrView.layer.cornerRadius = 8;
    self.qrView.image = [self connectedImage];
    [content addSubview:self.qrView];

    self.codeLabel = [self label:@"" size:38 weight:NSFontWeightSemibold];
    self.codeLabel.frame = NSMakeRect(24, 352, 392, 48);
    [content addSubview:self.codeLabel];

    self.expiryLabel = [self label:@"" size:13 weight:NSFontWeightRegular];
    self.expiryLabel.textColor = NSColor.secondaryLabelColor;
    self.expiryLabel.frame = NSMakeRect(24, 326, 392, 22);
    [content addSubview:self.expiryLabel];

    NSTextField *contentModeLabel = [self label:@"本机显示" size:12 weight:NSFontWeightMedium];
    contentModeLabel.alignment = NSTextAlignmentLeft;
    contentModeLabel.textColor = NSColor.secondaryLabelColor;
    contentModeLabel.frame = NSMakeRect(48, 316, 344, 20);
    [content addSubview:contentModeLabel];

    self.contentModeControl = [NSSegmentedControl
        segmentedControlWithLabels:@[@"完整", @"仅标题", @"仅来源"]
                    trackingMode:NSSegmentSwitchTrackingSelectOne
                          target:self
                          action:@selector(changeContentMode:)];
    self.contentModeControl.selectedSegment = 0;
    self.contentModeControl.frame = NSMakeRect(48, 282, 344, 30);
    [content addSubview:self.contentModeControl];

    self.pairButton = [NSButton buttonWithTitle:@"生成配对码"
                                         target:self
                                         action:@selector(startPairing:)];
    self.pairButton.bezelStyle = NSBezelStyleRounded;
    self.pairButton.keyEquivalent = @"\r";
    self.pairButton.frame = NSMakeRect(48, 224, 344, 44);
    [content addSubview:self.pairButton];

    NSTextField *diagnosticPrivacy = [self label:@"仅上传连接状态和错误代码，不包含通知正文或设备识别信息"
                                           size:11 weight:NSFontWeightRegular];
    diagnosticPrivacy.textColor = NSColor.secondaryLabelColor;
    diagnosticPrivacy.frame = NSMakeRect(24, 194, 392, 20);
    [content addSubview:diagnosticPrivacy];

    self.diagnosticButton = [NSButton buttonWithTitle:@"上传诊断日志"
                                                target:self
                                                action:@selector(uploadDiagnostics:)];
    self.diagnosticButton.bezelStyle = NSBezelStyleRounded;
    self.diagnosticButton.frame = NSMakeRect(48, 146, 344, 40);
    [content addSubview:self.diagnosticButton];

    self.diagnosticResultLabel = [self label:@"" size:11 weight:NSFontWeightRegular];
    self.diagnosticResultLabel.textColor = NSColor.secondaryLabelColor;
    self.diagnosticResultLabel.frame = NSMakeRect(24, 116, 392, 20);
    [content addSubview:self.diagnosticResultLabel];

    self.updateButton = [NSButton buttonWithTitle:@"检查更新"
                                            target:self
                                            action:@selector(checkForUpdates:)];
    self.updateButton.bezelStyle = NSBezelStyleRounded;
    self.updateButton.frame = NSMakeRect(48, 58, 344, 40);
    [content addSubview:self.updateButton];

    self.updateStatusLabel = [self label:@"版本 1.3.4 · 自动安全检查已开启"
                                    size:11 weight:NSFontWeightRegular];
    self.updateStatusLabel.textColor = NSColor.secondaryLabelColor;
    self.updateStatusLabel.frame = NSMakeRect(24, 28, 392, 20);
    [content addSubview:self.updateStatusLabel];
}

- (void)checkForUpdates:(id)sender {
    [self.updateManager checkForUpdatesInteractive:YES];
}

- (void)runStartupUpdateCheck {
    [self.updateManager checkForUpdatesInteractive:NO];
}

- (void)runBackgroundUpdateCheck:(NSTimer *)timer {
    [self.updateManager checkForUpdatesInteractive:NO];
}

- (void)changeContentMode:(NSSegmentedControl *)sender {
    NSArray<NSString *> *modes = @[@"full", @"title", @"source"];
    NSInteger selected = sender.selectedSegment;
    if (selected < 0 || selected >= (NSInteger)modes.count) return;
    self.contentMode = modes[selected];
    if (self.receiverId.length && self.receiverSecret.length && ![self saveCredential]) {
        self.receiverId = @"";
        self.receiverSecret = @"";
        self.receiverFingerprint = @"";
        self.pairingId = @"";
        self.credentialRecoveryRequired = YES;
        dispatch_async(dispatch_get_main_queue(), ^{
            self.pairButton.enabled = YES;
            [self setStatus:@"安全保存设备凭据失败，请重新配对" good:NO];
        });
        return;
    }
    [self restartAgent];
    NSArray<NSString *> *messages = @[
        @"设置成功：显示标题和正文",
        @"设置成功：仅显示通知标题",
        @"设置成功：仅显示来源 App"
    ];
    NSString *message = messages[selected];
    self.statusLabel.stringValue = message;
    self.statusLabel.textColor = NSColor.systemGreenColor;
    NSAlert *alert = [NSAlert new];
    alert.messageText = @"设置成功";
    alert.informativeText = message;
    [alert beginSheetModalForWindow:self.window completionHandler:nil];
}

- (void)setStatus:(NSString *)value good:(BOOL)good {
    dispatch_async(dispatch_get_main_queue(), ^{
        self.statusLabel.stringValue = value ?: @"";
        self.statusLabel.textColor = good ? NSColor.systemGreenColor : NSColor.secondaryLabelColor;
    });
}

- (void)setServerStatusCode:(NSString *)code text:(NSString *)text good:(BOOL)good {
    dispatch_async(dispatch_get_main_queue(), ^{
        self.serverStatusCode = code ?: @"unknown";
        if ([self.serverStatusCode isEqualToString:@"auth_failed"]) {
            self.credentialRecoveryRequired = YES;
        }
        self.serverStatusLabel.stringValue = text ?: @"服务器不可用";
        self.serverStatusLabel.textColor = good ? NSColor.systemGreenColor : NSColor.systemRedColor;
        BOOL hasCredential = self.receiverId.length && self.receiverSecret.length;
        if (self.credentialRecoveryRequired && hasCredential) {
            self.pairButton.title = @"清除失效凭据并重新配对";
            self.pairButton.enabled = YES;
        } else if ([self.pairButton.title isEqualToString:@"清除失效凭据并重新配对"]) {
            self.pairButton.title = hasCredential ? @"连接另一台手机" : @"生成配对码";
        }
    });
}

- (void)refreshServerStatus:(NSTimer *)timer {
    if (!HasNetworkConnection()) {
        [self setServerStatusCode:@"offline" text:@"无网络连接" good:NO];
        return;
    }
    BOOL authenticated = self.receiverId.length && self.receiverSecret.length;
    NSString *route = authenticated ? @"v1/device-status" : @"v1/health";
    NSArray<NSString *> *urls = @[
        [XXZFPublicBase stringByAppendingFormat:@"/%@", route]
    ];
    [self checkServerAtURLs:urls index:0 authenticated:authenticated];
}

- (void)checkServerAtURLs:(NSArray<NSString *> *)urls
                    index:(NSUInteger)index
            authenticated:(BOOL)authenticated {
    if (index >= urls.count) {
        NSString *code = HasNetworkConnection() ? @"unreachable" : @"offline";
        NSString *text = [code isEqualToString:@"offline"] ? @"无网络连接" : @"服务器不可用";
        [self setServerStatusCode:code text:text good:NO];
        return;
    }
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:[NSURL URLWithString:urls[index]]];
    request.timeoutInterval = 6;
    [request setValue:@"no-cache" forHTTPHeaderField:@"Cache-Control"];
    if (authenticated) {
        NSString *token = [NSString stringWithFormat:@"Bearer %@.%@", self.receiverId, self.receiverSecret];
        [request setValue:token forHTTPHeaderField:@"Authorization"];
    }
    NSURLSessionDataTask *task = [XXZFHTTPSession()
        dataTaskWithRequest:request completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        (void)data;
        NSHTTPURLResponse *http = (NSHTTPURLResponse *)response;
        if (!error && http.statusCode >= 200 && http.statusCode < 300) {
            if (authenticated) self.credentialRecoveryRequired = NO;
            [self setServerStatusCode:@"online" text:@"服务器在线" good:YES];
            return;
        }
        if (http.statusCode == 401 || http.statusCode == 403) {
            [self setServerStatusCode:@"auth_failed" text:@"需要重新连接" good:NO];
            return;
        }
        [self checkServerAtURLs:urls index:index + 1 authenticated:authenticated];
    }];
    [task resume];
}

- (NSArray *)diagnosticEntries {
    NSString *path = [[self supportDirectory] stringByAppendingPathComponent:@"diagnostics.jsonl"];
    NSString *raw = [NSString stringWithContentsOfFile:path encoding:NSUTF8StringEncoding error:nil];
    if (!raw.length) return @[];
    NSMutableArray *entries = [NSMutableArray array];
    for (NSString *line in [raw componentsSeparatedByCharactersInSet:NSCharacterSet.newlineCharacterSet]) {
        if (!line.length || entries.count >= 100) continue;
        NSData *data = [line dataUsingEncoding:NSUTF8StringEncoding];
        NSDictionary *source = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        if (![source isKindOfClass:NSDictionary.class]) continue;
        NSMutableDictionary *entry = [NSMutableDictionary dictionary];
        if (source[@"at"]) entry[@"at"] = source[@"at"];
        if (source[@"level"]) entry[@"level"] = source[@"level"];
        if (source[@"code"]) entry[@"code"] = source[@"code"];
        if (source[@"httpStatus"]) entry[@"httpStatus"] = source[@"httpStatus"];
        [entries addObject:entry];
    }
    return entries;
}

- (void)uploadDiagnostics:(id)sender {
    if (!self.receiverId.length || !self.receiverSecret.length) {
        self.diagnosticResultLabel.stringValue = @"请先连接手机后再上传";
        self.diagnosticResultLabel.textColor = NSColor.systemRedColor;
        return;
    }
    if (!HasNetworkConnection()) {
        self.diagnosticResultLabel.stringValue = @"无网络连接";
        self.diagnosticResultLabel.textColor = NSColor.systemRedColor;
        return;
    }
    self.diagnosticButton.enabled = NO;
    self.diagnosticResultLabel.stringValue = @"正在安全上传";
    NSDictionary *info = NSBundle.mainBundle.infoDictionary;
    NSDictionary *body = @{
        @"appVersion": info[@"CFBundleShortVersionString"] ?: @"",
        @"platformVersion": NSProcessInfo.processInfo.operatingSystemVersionString ?: @"",
        @"networkStatus": @"online",
        @"serverStatus": self.serverStatusCode ?: @"unknown",
        @"paired": @YES,
        @"listenerEnabled": @YES,
        @"backgroundRestricted": @NO,
        @"entries": [self diagnosticEntries]
    };
    NSData *data = [NSJSONSerialization dataWithJSONObject:body options:0 error:nil];
    NSArray<NSString *> *urls = @[
        [XXZFPublicBase stringByAppendingString:@"/v1/diagnostics"]
    ];
    [self uploadDiagnosticsAtURLs:urls index:0 body:data];
}

- (void)uploadDiagnosticsAtURLs:(NSArray<NSString *> *)urls index:(NSUInteger)index body:(NSData *)body {
    if (index >= urls.count) {
        dispatch_async(dispatch_get_main_queue(), ^{
            self.diagnosticButton.enabled = YES;
            self.diagnosticResultLabel.stringValue = @"服务器不可用";
            self.diagnosticResultLabel.textColor = NSColor.systemRedColor;
        });
        return;
    }
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:[NSURL URLWithString:urls[index]]];
    request.HTTPMethod = @"POST";
    request.HTTPBody = body;
    request.timeoutInterval = 8;
    [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    NSString *token = [NSString stringWithFormat:@"Bearer %@.%@", self.receiverId, self.receiverSecret];
    [request setValue:token forHTTPHeaderField:@"Authorization"];
    NSURLSessionDataTask *task = [XXZFHTTPSession()
        dataTaskWithRequest:request completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSHTTPURLResponse *http = (NSHTTPURLResponse *)response;
        NSDictionary *json = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        if (!error && http.statusCode >= 200 && http.statusCode < 300 && [json[@"ok"] boolValue]) {
            NSString *diagnosticId = [json[@"diagnosticId"] description] ?: @"";
            dispatch_async(dispatch_get_main_queue(), ^{
                self.diagnosticButton.enabled = YES;
                self.diagnosticResultLabel.stringValue = [NSString stringWithFormat:@"上传成功 · 诊断编号 %@", diagnosticId];
                self.diagnosticResultLabel.textColor = NSColor.systemGreenColor;
                NSAlert *alert = [NSAlert new];
                alert.messageText = @"诊断日志上传成功";
                alert.informativeText = [NSString stringWithFormat:@"诊断编号：%@", diagnosticId];
                [alert beginSheetModalForWindow:self.window completionHandler:nil];
            });
            return;
        }
        if (http.statusCode == 401 || http.statusCode == 403 || http.statusCode == 429) {
            dispatch_async(dispatch_get_main_queue(), ^{
                self.diagnosticButton.enabled = YES;
                self.diagnosticResultLabel.stringValue = http.statusCode == 429
                    ? @"上传过于频繁，请稍后再试" : @"需要重新连接";
                self.diagnosticResultLabel.textColor = NSColor.systemRedColor;
            });
            return;
        }
        [self uploadDiagnosticsAtURLs:urls index:index + 1 body:body];
    }];
    [task resume];
}

- (void)startPairing:(id)sender {
    if (self.credentialRecoveryRequired
            && self.receiverId.length && self.receiverSecret.length) {
        [self confirmCredentialRecovery];
        return;
    }
    self.pairingSuccessShown = NO;
    self.credentialRecoveryRequired = NO;
    self.pairButton.enabled = NO;
    [self setStatus:@"正在连接通知服务" good:NO];
    NSArray<NSString *> *urls = @[
        [XXZFPublicBase stringByAppendingString:@"/pair/start"]
    ];
    [self requestPairingAtURLs:urls index:0];
}

- (void)requestPairingAtURLs:(NSArray<NSString *> *)urls index:(NSUInteger)index {
    if (index >= urls.count) {
        dispatch_async(dispatch_get_main_queue(), ^{
            self.pairButton.enabled = YES;
            [self setStatus:@"通知服务暂不可用，请检查网络" good:NO];
        });
        return;
    }

    NSURL *url = [NSURL URLWithString:urls[index]];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
    request.HTTPMethod = @"POST";
    [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    if (self.receiverId.length && self.receiverSecret.length) {
        NSString *token = [NSString stringWithFormat:@"Bearer %@.%@", self.receiverId, self.receiverSecret];
        [request setValue:token forHTTPHeaderField:@"Authorization"];
    }
    NSString *host = NSHost.currentHost.localizedName ?: @"Mac";
    NSDictionary *body = @{@"deviceName": [host stringByAppendingString:@" 的 Mac"],
                           @"platform": @"macos"};
    request.HTTPBody = [NSJSONSerialization dataWithJSONObject:body options:0 error:nil];
    request.timeoutInterval = 7;

    NSURLSessionDataTask *task = [XXZFHTTPSession()
        dataTaskWithRequest:request
          completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSHTTPURLResponse *http = (NSHTTPURLResponse *)response;
        if (http.statusCode == 401 || http.statusCode == 403) {
            [self setServerStatusCode:@"auth_failed" text:@"设备凭据已失效 · 需要重新配对" good:NO];
            dispatch_async(dispatch_get_main_queue(), ^{
                self.pairButton.enabled = YES;
                [self setStatus:@"服务器已拒绝本机凭据，请确认后重新配对" good:NO];
            });
            return;
        }
        if (error || http.statusCode < 200 || http.statusCode >= 300) {
            [self requestPairingAtURLs:urls index:index + 1];
            return;
        }
        NSDictionary *json = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        NSDictionary *pairing = json[@"pairing"];
        if (![json[@"ok"] boolValue] || ![pairing isKindOfClass:NSDictionary.class]) {
            [self requestPairingAtURLs:urls index:index + 1];
            return;
        }
        [self acceptPairing:pairing];
    }];
    [task resume];
}

- (void)confirmCredentialRecovery {
    NSAlert *alert = [NSAlert new];
    alert.alertStyle = NSAlertStyleWarning;
    alert.messageText = @"清除失效凭据并重新配对？";
    alert.informativeText = @"服务器已拒绝这台 Mac 的设备凭据。只有你确认后，"
        @"应用才会清除本机失效凭据并创建新配对码；不会静默切换为匿名连接。";
    [alert addButtonWithTitle:@"取消"];
    [alert addButtonWithTitle:@"清除并重新配对"];
    [alert beginSheetModalForWindow:self.window completionHandler:^(NSModalResponse response) {
        if (response != NSAlertSecondButtonReturn) return;
        if (![self clearCredentialForRecovery]) {
            [self setStatus:@"本机凭据清除失败，已保留原凭据" good:NO];
            return;
        }
        self.serverStatusCode = @"unknown";
        [self startPairing:nil];
    }];
}

- (BOOL)writeCredentialConfiguration:(NSDictionary *)value {
    NSFileManager *files = NSFileManager.defaultManager;
    [files createDirectoryAtPath:[self supportDirectory]
     withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions: @(0700)} error:nil];
    chmod(self.supportDirectory.fileSystemRepresentation, 0700);
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingPrettyPrinted error:nil];
    NSError *writeError = nil;
    if (!data || ![data writeToFile:[self credentialPath]
                             options:NSDataWritingAtomic
                               error:&writeError]) return NO;
    chmod(self.credentialPath.fileSystemRepresentation, 0600);
    return YES;
}

- (BOOL)clearCredentialForRecovery {
    if (!XXZFDeleteReceiverSecret()) return NO;
    NSDictionary *value = @{
        @"contentMode": self.contentMode ?: @"full",
        @"showContent": @(![self.contentMode isEqualToString:@"source"]),
        @"servers": @[XXZFPublicBase]
    };
    if (![self writeCredentialConfiguration:value]) {
        [NSFileManager.defaultManager removeItemAtPath:[self credentialPath] error:nil];
        if ([NSFileManager.defaultManager fileExistsAtPath:[self credentialPath]]) return NO;
    }

    self.receiverId = @"";
    self.receiverSecret = @"";
    self.receiverFingerprint = @"";
    self.pairingId = @"";
    self.expiresAt = 0;
    self.pairingSuccessShown = NO;
    self.credentialRecoveryRequired = NO;
    [self.timer invalidate];
    self.timer = nil;
    self.codeLabel.stringValue = @"";
    self.expiryLabel.stringValue = @"";
    self.qrView.layer.backgroundColor = NSColor.clearColor.CGColor;
    self.qrView.image = [self connectedImage];
    self.pairButton.title = @"生成配对码";
    [self restartAgent];
    return YES;
}

- (void)acceptPairing:(NSDictionary *)pairing {
    NSString *receiverId = [pairing[@"receiverId"] description];
    NSString *receiverSecret = [pairing[@"receiverSecret"] description];
    if (receiverId.length) self.receiverId = receiverId;
    if (receiverSecret.length) self.receiverSecret = receiverSecret;
    self.credentialRecoveryRequired = NO;
    self.receiverFingerprint = [pairing[@"receiverFingerprint"] description];
    self.expiresAt = [pairing[@"expiresAt"] longLongValue];
    self.pairingId = [pairing[@"pairingId"] description];
    NSString *code = [pairing[@"code"] description];
    NSString *payload = [pairing[@"qrPayload"] description];
    if (![self saveCredential]) {
        self.receiverId = @"";
        self.receiverSecret = @"";
        self.receiverFingerprint = @"";
        self.pairingId = @"";
        self.credentialRecoveryRequired = YES;
        dispatch_async(dispatch_get_main_queue(), ^{
            self.pairButton.enabled = YES;
            [self setStatus:@"安全保存设备凭据失败，请重新配对" good:NO];
        });
        return;
    }
    [self restartAgent];

    dispatch_async(dispatch_get_main_queue(), ^{
        self.pairButton.enabled = YES;
        self.pairButton.title = @"重新生成";
        self.codeLabel.stringValue = code ?: @"";
        self.qrView.layer.backgroundColor = NSColor.whiteColor.CGColor;
        self.qrView.image = [self qrImage:payload];
        [self setStatus:@"等待手机扫码或输入配对码" good:NO];
        [self.timer invalidate];
        self.timer = [NSTimer scheduledTimerWithTimeInterval:1
                                                     target:self
                                                   selector:@selector(updatePairingState:)
                                                   userInfo:nil
                                                    repeats:YES];
        [self updatePairingState:nil];
    });
}

- (NSImage *)qrImage:(NSString *)payload {
    NSData *data = [payload dataUsingEncoding:NSUTF8StringEncoding];
    CIFilter *filter = [CIFilter filterWithName:@"CIQRCodeGenerator"];
    [filter setValue:data forKey:@"inputMessage"];
    [filter setValue:@"M" forKey:@"inputCorrectionLevel"];
    CIImage *image = filter.outputImage;
    if (!image) return nil;
    CGFloat scale = floor(200.0 / image.extent.size.width);
    CIImage *scaled = [image imageByApplyingTransform:CGAffineTransformMakeScale(scale, scale)];
    NSCIImageRep *representation = [NSCIImageRep imageRepWithCIImage:scaled];
    NSImage *result = [[NSImage alloc] initWithSize:representation.size];
    [result addRepresentation:representation];
    return result;
}

- (NSImage *)connectedImage {
    NSString *path = [NSBundle.mainBundle pathForResource:@"AppIcon" ofType:@"png"];
    return path.length ? [[NSImage alloc] initWithContentsOfFile:path] : nil;
}

- (void)updatePairingState:(NSTimer *)timer {
    long long remaining = MAX(0, (self.expiresAt - (long long)(NSDate.date.timeIntervalSince1970 * 1000)) / 1000);
    self.expiryLabel.stringValue = remaining > 0
        ? [NSString stringWithFormat:@"%lld 秒后失效 · 设备编号 %@", remaining, self.receiverFingerprint ?: @""]
        : @"配对码已失效";
    if (remaining <= 0) {
        [self.timer invalidate];
        return;
    }
    [self pollStatus];
}

- (void)pollStatus {
    if (!self.receiverId.length || !self.receiverSecret.length) return;
    NSString *query = self.pairingId.length
        ? [NSString stringWithFormat:@"?pairingId=%@", self.pairingId] : @"";
    NSArray<NSString *> *urls = @[
        [XXZFPublicBase stringByAppendingString:@"/pair/status"]
    ];
    NSMutableArray<NSString *> *qualified = [NSMutableArray arrayWithCapacity:urls.count];
    for (NSString *url in urls) [qualified addObject:[url stringByAppendingString:query]];
    [self pollStatusAtURLs:qualified index:0];
}

- (void)pollStatusAtURLs:(NSArray<NSString *> *)urls index:(NSUInteger)index {
    if (index >= urls.count) return;
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:[NSURL URLWithString:urls[index]]];
    NSString *token = [NSString stringWithFormat:@"Bearer %@.%@", self.receiverId, self.receiverSecret];
    [request setValue:token forHTTPHeaderField:@"Authorization"];
    request.timeoutInterval = 5;
    NSURLSessionDataTask *task = [XXZFHTTPSession()
        dataTaskWithRequest:request
          completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        NSHTTPURLResponse *http = (NSHTTPURLResponse *)response;
        if (http.statusCode == 401 || http.statusCode == 403) {
            [self setServerStatusCode:@"auth_failed" text:@"设备凭据已失效 · 需要重新配对" good:NO];
            dispatch_async(dispatch_get_main_queue(), ^{
                [self.timer invalidate];
                self.timer = nil;
                self.pairButton.enabled = YES;
                [self setStatus:@"服务器已拒绝本机凭据，请确认后重新配对" good:NO];
            });
            return;
        }
        if (error || http.statusCode < 200 || http.statusCode >= 300) {
            [self pollStatusAtURLs:urls index:index + 1];
            return;
        }
        NSDictionary *json = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        if ([json[@"paired"] boolValue]) {
            dispatch_async(dispatch_get_main_queue(), ^{
                self.credentialRecoveryRequired = NO;
                [self.timer invalidate];
                self.qrView.layer.backgroundColor = NSColor.clearColor.CGColor;
                self.qrView.image = [self connectedImage];
                self.pairingId = @"";
                self.codeLabel.stringValue = @"已连接";
                self.expiryLabel.stringValue = [NSString stringWithFormat:@"设备编号 %@", self.receiverFingerprint ?: @""];
                self.pairButton.title = @"连接另一台手机";
                [self setStatus:@"后台接收已启动" good:YES];
                if (!self.pairingSuccessShown) {
                    self.pairingSuccessShown = YES;
                    NSAlert *alert = [NSAlert new];
                    alert.messageText = @"配对成功";
                    alert.informativeText = @"这台 Mac 已准备好接收通知";
                    [alert beginSheetModalForWindow:self.window completionHandler:nil];
                }
            });
        }
    }];
    [task resume];
}

- (NSString *)supportDirectory {
    return XXZFSupportDirectory();
}

- (NSString *)credentialPath {
    return [[self supportDirectory] stringByAppendingPathComponent:@"receiver.json"];
}

- (BOOL)saveCredential {
    if (!self.receiverId.length || !self.receiverSecret.length) return NO;
    if (!XXZFStoreReceiverSecret(self.receiverSecret)) return NO;
    NSDictionary *value = @{
        @"receiverId": self.receiverId,
        @"receiverFingerprint": self.receiverFingerprint ?: @"",
        @"contentMode": self.contentMode ?: @"full",
        @"showContent": @(![self.contentMode isEqualToString:@"source"]),
        @"servers": @[XXZFPublicBase]
    };
    if ([self writeCredentialConfiguration:value]) return YES;
    XXZFDeleteReceiverSecret();
    return NO;
}

- (void)loadCredential {
    NSData *data = [NSData dataWithContentsOfFile:[self credentialPath]];
    NSDictionary *value = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    if (![value isKindOfClass:NSDictionary.class]) return;
    self.receiverId = [value[@"receiverId"] isKindOfClass:NSString.class]
        ? value[@"receiverId"] : @"";
    self.receiverFingerprint = [value[@"receiverFingerprint"] description];
    NSString *contentMode = [value[@"contentMode"] description];
    if (![@[@"full", @"title", @"source"] containsObject:contentMode]) {
        NSNumber *showContent = value[@"showContent"];
        contentMode = (!showContent || showContent.boolValue) ? @"full" : @"source";
    }
    self.contentMode = contentMode;
    self.contentModeControl.selectedSegment = [@[@"full", @"title", @"source"] indexOfObject:contentMode];
    NSString *legacySecret = [value[@"receiverSecret"] isKindOfClass:NSString.class]
        ? value[@"receiverSecret"] : @"";
    if (legacySecret.length) {
        BOOL stored = XXZFStoreReceiverSecret(legacySecret);
        NSMutableDictionary *sanitized = [value mutableCopy];
        [sanitized removeObjectForKey:@"receiverSecret"];
        sanitized[@"servers"] = @[XXZFPublicBase];
        BOOL removedFromDisk = [self writeCredentialConfiguration:sanitized];
        if (!removedFromDisk) {
            [NSFileManager.defaultManager removeItemAtPath:[self credentialPath] error:nil];
            removedFromDisk = ![NSFileManager.defaultManager fileExistsAtPath:[self credentialPath]];
        }
        if (!stored || !removedFromDisk) {
            XXZFDeleteReceiverSecret();
            self.receiverSecret = @"";
            self.credentialRecoveryRequired = YES;
            [self setStatus:@"旧凭据安全迁移失败，请重新配对" good:NO];
            return;
        }
    }
    if (!self.receiverId.length) {
        XXZFDeleteReceiverSecret();
        return;
    }
    self.receiverSecret = XXZFCopyReceiverSecret() ?: @"";
    if (self.receiverId.length && !self.receiverSecret.length) {
        self.credentialRecoveryRequired = YES;
        [self setStatus:@"钥匙串凭据不可用，请重新配对" good:NO];
        self.pairButton.title = @"清除失效凭据并重新配对";
        return;
    }
    if (self.receiverId.length && self.receiverSecret.length) {
        self.pairingSuccessShown = YES;
        self.qrView.layer.backgroundColor = NSColor.clearColor.CGColor;
        self.qrView.image = [self connectedImage];
        self.codeLabel.stringValue = @"已连接";
        self.expiryLabel.stringValue = [NSString stringWithFormat:@"设备编号 %@", self.receiverFingerprint ?: @""];
        self.pairButton.title = @"连接另一台手机";
        [self setStatus:@"后台接收已启动" good:YES];
        [self pollStatus];
    }
}

- (void)installRuntime {
    NSFileManager *files = NSFileManager.defaultManager;
    NSString *support = [self supportDirectory];
    [files createDirectoryAtPath:support
     withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions: @(0700)} error:nil];
    chmod(support.fileSystemRepresentation, 0700);
    NSString *resources = NSBundle.mainBundle.resourcePath;
    for (NSString *name in @[@"mac_client.py", @"mac_client_core.py"]) {
        NSString *source = [resources stringByAppendingPathComponent:name];
        NSString *target = [support stringByAppendingPathComponent:name];
        if ([files fileExistsAtPath:source]) {
            [files removeItemAtPath:target error:nil];
            [files copyItemAtPath:source toPath:target error:nil];
            chmod(target.fileSystemRepresentation, 0600);
        }
    }

    for (NSString *name in @[@"xxzf-air-notifier.log", @"xxzf-air-notifier.err.log"]) {
        NSString *path = [support stringByAppendingPathComponent:name];
        if (![files fileExistsAtPath:path]) [files createFileAtPath:path contents:NSData.data attributes:nil];
        chmod(path.fileSystemRepresentation, 0600);
    }

    NSString *launchAgents = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/LaunchAgents"];
    [files createDirectoryAtPath:launchAgents withIntermediateDirectories:YES attributes:nil error:nil];
    NSString *agentPath = [launchAgents stringByAppendingPathComponent:@"com.zundu.xxzf.air-notifier.plist"];
    NSString *agentExecutable = NSBundle.mainBundle.executablePath;
    NSDictionary *agent = @{
        @"Label": @"com.zundu.xxzf.air-notifier",
        @"ProgramArguments": @[agentExecutable, @"--agent"],
        @"EnvironmentVariables": @{@"XXZF_NOTIFIER_APP": NSBundle.mainBundle.bundlePath},
        @"WorkingDirectory": support,
        @"RunAtLoad": @YES,
        @"KeepAlive": @YES,
        @"Umask": @63,
        @"StandardOutPath": [support stringByAppendingPathComponent:@"xxzf-air-notifier.log"],
        @"StandardErrorPath": [support stringByAppendingPathComponent:@"xxzf-air-notifier.err.log"]
    };
    [agent writeToFile:agentPath atomically:YES];
    [self restartAgent];
}

- (void)restartAgent {
    NSString *agent = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/LaunchAgents/com.zundu.xxzf.air-notifier.plist"];
    NSString *uid = [NSString stringWithFormat:@"gui/%u", getuid()];
    NSTask *bootout = [[NSTask alloc] init];
    bootout.launchPath = @"/bin/launchctl";
    bootout.arguments = @[@"bootout", uid, agent];
    [bootout launch];
    [bootout waitUntilExit];

    NSString *runner = [XXZFSupportDirectory() stringByAppendingPathComponent:@"mac_client.py"];
    NSString *pattern = [NSString stringWithFormat:@"%@ --credentials-stdin$",
                         [NSRegularExpression escapedPatternForString:runner]];
    NSTask *terminateClients = [[NSTask alloc] init];
    terminateClients.launchPath = @"/usr/bin/pkill";
    terminateClients.arguments = @[@"-TERM", @"-f", pattern];
    [terminateClients launch];
    [terminateClients waitUntilExit];
    [NSThread sleepForTimeInterval:0.25];

    NSTask *bootstrap = [[NSTask alloc] init];
    bootstrap.launchPath = @"/bin/launchctl";
    bootstrap.arguments = @[@"bootstrap", uid, agent];
    [bootstrap launch];
}

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSString *firstArgument = argc > 1 ? [NSString stringWithUTF8String:argv[1]] : @"";
        if ([firstArgument isEqualToString:@"--notify"]) {
            NSApplication *notificationApplication = NSApplication.sharedApplication;
            notificationApplication.activationPolicy = NSApplicationActivationPolicyAccessory;
            [notificationApplication finishLaunching];
            NSString *title = argc > 2 ? [NSString stringWithUTF8String:argv[2]] : @"转发";
            NSString *body = argc > 3 ? [NSString stringWithUTF8String:argv[3]] : @"";
            XXZFNotificationDelegate *notificationDelegate = [XXZFNotificationDelegate new];
            return DeliverNotification(title, body, notificationDelegate);
        }
        if ([firstArgument isEqualToString:@"--clear"]) {
            [UNUserNotificationCenter.currentNotificationCenter removeAllPendingNotificationRequests];
            [UNUserNotificationCenter.currentNotificationCenter removeAllDeliveredNotifications];
            [NSUserNotificationCenter.defaultUserNotificationCenter removeAllDeliveredNotifications];
            return 0;
        }
        if ([firstArgument isEqualToString:@"--agent"]) {
            return XXZFRunBackgroundAgent();
        }
        NSApplication *application = NSApplication.sharedApplication;
        application.activationPolicy = NSApplicationActivationPolicyRegular;
        ReceiverDelegate *delegate = [[ReceiverDelegate alloc] init];
        application.delegate = delegate;
        [application run];
    }
    return 0;
}
