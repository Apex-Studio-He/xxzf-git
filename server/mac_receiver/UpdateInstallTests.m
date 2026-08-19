#import <Cocoa/Cocoa.h>

#import "UpdateManager.h"

@interface XXZFUpdateManager (InstallTests)
- (BOOL)stageDMGAtPath:(NSString *)dmg
              manifest:(NSDictionary *)manifest
                 error:(NSError **)error;
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 4) return 2;
        NSString *version = [NSString stringWithUTF8String:argv[2]];
        NSInteger versionCode = [[NSString stringWithUTF8String:argv[3]] integerValue];
        if (!version.length || versionCode < 2) return 2;
        XXZFUpdateManager *manager = [[XXZFUpdateManager alloc]
            initWithOwnerWindow:(NSWindow *)nil
             currentVersionCode:versionCode - 1
                 currentVersion:@"previous"
                  statusHandler:^(__unused NSString *status, __unused BOOL isError) {}];
        NSDictionary *manifest = @{
            @"version": version,
            @"versionCode": @(versionCode)
        };
        NSError *error = nil;
        BOOL success = [manager stageDMGAtPath:[NSString stringWithUTF8String:argv[1]]
                                      manifest:manifest error:&error];
        if (!success) {
            fprintf(stderr, "FAIL: %s\n", error.localizedDescription.UTF8String);
            return 1;
        }
        NSString *staged = [NSHomeDirectory()
            stringByAppendingPathComponent:@"Library/Application Support/XXZF/update/staged/转发.app"];
        NSBundle *bundle = [NSBundle bundleWithPath:staged];
        if (![bundle.bundleIdentifier isEqual:@"com.zundu.xxzf.notifier"]
                || ![bundle.infoDictionary[@"CFBundleShortVersionString"] isEqual:version]
                || [bundle.infoDictionary[@"CFBundleVersion"] integerValue] != versionCode) return 1;
        puts("PASS: verified read-only DMG, bundle identity, version and code signature");
    }
    return 0;
}
