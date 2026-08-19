#import <Foundation/Foundation.h>

#import "UpdateManager.h"

static void Require(BOOL condition, NSString *message) {
    if (!condition) {
        fprintf(stderr, "FAIL: %s\n", message.UTF8String);
        exit(1);
    }
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        Require(argc == 3, @"expected manifest and package paths");
        NSData *manifestData = [NSData dataWithContentsOfFile:
            [NSString stringWithUTF8String:argv[1]]];
        NSString *packagePath = [NSString stringWithUTF8String:argv[2]];
        NSError *error = nil;
        NSDictionary *valid = [XXZFUpdateManager validatedManifestFromData:manifestData
                                                         currentVersionCode:14 error:&error];
        if (!valid) fprintf(stderr, "validation error: %s\n", error.localizedDescription.UTF8String);
        Require(valid != nil && error == nil, @"valid signed manifest rejected");
        Require([XXZFUpdateManager verifyFileAtPath:packagePath
                                       expectedSize:[valid[@"size"] unsignedLongLongValue]
                                     expectedSHA256:valid[@"sha256"] error:&error],
                @"valid package digest rejected");

        NSMutableDictionary *changed = [valid mutableCopy];
        changed[@"notes"] = @"tampered";
        NSData *changedData = [NSJSONSerialization dataWithJSONObject:changed options:0 error:nil];
        Require([XXZFUpdateManager validatedManifestFromData:changedData
                                           currentVersionCode:14 error:nil] == nil,
                @"tampered signature accepted");

        for (NSString *key in @[@"platform", @"url", @"keyId"]) {
            changed = [valid mutableCopy];
            changed[key] = @"invalid";
            changedData = [NSJSONSerialization dataWithJSONObject:changed options:0 error:nil];
            Require([XXZFUpdateManager validatedManifestFromData:changedData
                                               currentVersionCode:14 error:nil] == nil,
                    [NSString stringWithFormat:@"invalid %@ accepted", key]);
        }
        Require([XXZFUpdateManager validatedManifestFromData:manifestData
                                           currentVersionCode:15 error:nil] == nil,
                @"same version accepted");
        Require(![XXZFUpdateManager verifyFileAtPath:packagePath
                                        expectedSize:[valid[@"size"] unsignedLongLongValue] + 1
                                      expectedSHA256:valid[@"sha256"] error:nil],
                @"wrong package size accepted");
        Require(![XXZFUpdateManager verifyFileAtPath:packagePath
                                        expectedSize:[valid[@"size"] unsignedLongLongValue]
                                      expectedSHA256:[@"0" stringByPaddingToLength:64
                                                                        withString:@"0"
                                                                   startingAtIndex:0]
                                               error:nil],
                @"wrong package hash accepted");
        puts("PASS: macOS update manifest and package validation");
    }
    return 0;
}
