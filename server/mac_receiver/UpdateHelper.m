#import <Foundation/Foundation.h>

#include <signal.h>
#include <sys/stat.h>
#include <unistd.h>

static int RunTask(NSString *path, NSArray<NSString *> *arguments) {
    NSTask *task = [NSTask new];
    task.launchPath = path;
    task.arguments = arguments;
    task.standardOutput = [NSPipe pipe];
    task.standardError = [NSPipe pipe];
    @try {
        [task launch];
        [task waitUntilExit];
        return task.terminationStatus;
    } @catch (__unused NSException *exception) {
        return -1;
    }
}

static NSString *CodeDirectoryHash(NSString *appPath) {
    NSPipe *detailsPipe = [NSPipe pipe];
    NSTask *task = [NSTask new];
    task.launchPath = @"/usr/bin/codesign";
    task.arguments = @[@"-d", @"--verbose=4", appPath];
    task.standardOutput = [NSPipe pipe];
    task.standardError = detailsPipe;
    @try {
        [task launch];
        [task waitUntilExit];
    } @catch (__unused NSException *exception) {
        return nil;
    }
    if (task.terminationStatus != 0) return nil;
    NSData *data = [detailsPipe.fileHandleForReading readDataToEndOfFile];
    NSString *text = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    for (NSString *line in [text componentsSeparatedByCharactersInSet:NSCharacterSet.newlineCharacterSet]) {
        if ([line hasPrefix:@"CDHash="]) return [line substringFromIndex:7];
    }
    return nil;
}

static BOOL IsLowercaseHex(NSString *value) {
    if (!(value.length == 40 || value.length == 64)) return NO;
    NSCharacterSet *allowed = [NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"];
    return [value rangeOfCharacterFromSet:allowed.invertedSet].location == NSNotFound;
}

static BOOL IsStrictPositiveInteger(NSString *value) {
    if (!value.length || value.length > 12) return NO;
    NSCharacterSet *digits = NSCharacterSet.decimalDigitCharacterSet;
    return [value rangeOfCharacterFromSet:digits.invertedSet].location == NSNotFound
        && value.longLongValue > 0;
}

static BOOL PathHasSymlinkComponent(NSString *path) {
    NSString *standard = path.stringByStandardizingPath;
    if (![standard hasPrefix:@"/"]) return YES;
    NSString *current = @"/";
    for (NSString *component in standard.pathComponents) {
        if ([component isEqualToString:@"/"]) continue;
        current = [current stringByAppendingPathComponent:component];
        struct stat info;
        if (lstat(current.fileSystemRepresentation, &info) == 0 && S_ISLNK(info.st_mode)) {
            return YES;
        }
    }
    return NO;
}

static BOOL ValidateBundle(NSString *path, NSString *version, NSInteger versionCode,
                           NSString *expectedCodeDirectoryHash) {
    NSBundle *bundle = [NSBundle bundleWithPath:path];
    NSDictionary *info = bundle.infoDictionary;
    return bundle
        && [bundle.bundleIdentifier isEqual:@"com.zundu.xxzf.notifier"]
        && [info[@"CFBundleShortVersionString"] isEqual:version]
        && [info[@"CFBundleVersion"] integerValue] == versionCode
        && RunTask(@"/usr/bin/codesign", @[@"--verify", @"--deep", @"--strict", path]) == 0
        && [CodeDirectoryHash(path) isEqual:expectedCodeDirectoryHash];
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 7 || strcmp(argv[1], "--apply") != 0) return 2;
        NSString *target = [[NSString stringWithUTF8String:argv[2]] stringByStandardizingPath];
        NSString *version = [NSString stringWithUTF8String:argv[3]];
        NSString *versionCodeText = [NSString stringWithUTF8String:argv[4]];
        NSString *codeDirectoryHash = [NSString stringWithUTF8String:argv[5]];
        NSString *pidText = [NSString stringWithUTF8String:argv[6]];
        NSString *systemTarget = @"/Applications/转发.app";
        NSString *userTarget = [[NSHomeDirectory() stringByAppendingPathComponent:@"Applications/转发.app"]
            stringByStandardizingPath];
        NSRange versionMatch = [version rangeOfString:@"^[0-9]+\\.[0-9]+\\.[0-9]+$"
                                               options:NSRegularExpressionSearch];
        if (!([target isEqualToString:systemTarget] || [target isEqualToString:userTarget])
                || PathHasSymlinkComponent(target)
                || versionMatch.location != 0 || versionMatch.length != version.length
                || !IsStrictPositiveInteger(versionCodeText)
                || !IsLowercaseHex(codeDirectoryHash)
                || !IsStrictPositiveInteger(pidText)) return 3;

        NSString *updateRoot = [NSHomeDirectory()
            stringByAppendingPathComponent:@"Library/Application Support/XXZF/update"];
        NSString *staged = [updateRoot stringByAppendingPathComponent:@"staged/转发.app"];
        NSString *backupParent = [updateRoot stringByAppendingPathComponent:@"backup"];
        NSString *backup = [backupParent stringByAppendingPathComponent:@"转发.app"];
        NSInteger versionCode = versionCodeText.integerValue;
        if (PathHasSymlinkComponent(updateRoot) || PathHasSymlinkComponent(staged)
                || !ValidateBundle(staged, version, versionCode, codeDirectoryHash)) return 4;

        pid_t parentPID = (pid_t)pidText.intValue;
        for (NSUInteger attempt = 0; attempt < 300 && kill(parentPID, 0) == 0; attempt++) {
            usleep(100000);
        }
        if (kill(parentPID, 0) == 0) return 5;

        NSFileManager *files = NSFileManager.defaultManager;
        [files removeItemAtPath:backupParent error:nil];
        NSError *error = nil;
        if (![files createDirectoryAtPath:backupParent withIntermediateDirectories:YES
                               attributes:@{NSFilePosixPermissions: @(0700)} error:&error]) return 6;
        chmod(backupParent.fileSystemRepresentation, 0700);
        if (![files moveItemAtPath:target toPath:backup error:&error]) return 7;
        if (![files moveItemAtPath:staged toPath:target error:&error]
                || !ValidateBundle(target, version, versionCode, codeDirectoryHash)) {
            [files removeItemAtPath:target error:nil];
            [files moveItemAtPath:backup toPath:target error:nil];
            return 8;
        }
        if (RunTask(@"/usr/bin/open", @[@"-n", target]) != 0) {
            [files removeItemAtPath:target error:nil];
            [files moveItemAtPath:backup toPath:target error:nil];
            RunTask(@"/usr/bin/open", @[@"-n", target]);
            return 9;
        }
        [files removeItemAtPath:backupParent error:nil];
        return 0;
    }
}
