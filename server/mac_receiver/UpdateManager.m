#import "UpdateManager.h"

#import <CommonCrypto/CommonDigest.h>
#import <Security/Security.h>
#include <sys/stat.h>
#include <unistd.h>

static NSString *const XXZFUpdateManifestURL =
    @"https://updates.example.com/downloads/forwarder/test/macos.json";
static NSString *const XXZFUpdateBaseURL =
    @"https://updates.example.com/downloads/forwarder/test";
static NSString *const XXZFUpdateKeyId = @"8545bd8392ab5de2";
#ifdef XXZF_TEST_PUBLIC_KEY_BASE64
static NSString *const XXZFUpdatePublicKey = @XXZF_TEST_PUBLIC_KEY_BASE64;
#else
static NSString *const XXZFUpdatePublicKey =
    @"MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAvtEyLwpBwuLl3beIHljcyva1LI9BStCnW7ml3XZllEHsTRU2DJ/gb8D6ElvocBr0BjKxtgMJAb/RQoh7AL+U8EZ+QTooT6DZC7tMxxu4C0J9Mg9UFAIA8WVdXEOsSoqjeXYanMYZDiZ21SrklCl5mIYsL5f6wOnSBd+Oy18yUiaCX87YirxkfBH3ooNEDXAT61tc9ieNBFo4Wr4/2yeB7DC+xFAzKBNMwQBzRqEwNkD/w0kUh/k0zs0VDz35RwNoI46XzC6e8UUVwKbNg6GO/9dvtpgyZDEqP1Ldr3T3c3hHLDKmiaklYexO9P43vO1exff2EBt4oTU0NBdUZvyvkFhZQjGWDqAycpdgdzVCRJcCFHBVBvEHWeTCXbaJyBLAv41SJ4a92iiwj3+1qw5yaVIWw9e8aGBVXTu7G8cMU6r5/XN/UF+u449fVneVCMQZ+wDfwrc0h29IY+y+RzMHQrz9yHkv1YiFmL/00K/c4Bpgu0TeurMI33M/W3u1bTJ/AgMBAAE=";
#endif
static NSString *const XXZFUpdateErrorDomain = @"com.zundu.xxzf.update";
static unsigned long long const XXZFMaximumPackageSize = 256ULL * 1024ULL * 1024ULL;
static NSUInteger const XXZFMaximumManifestSize = 64 * 1024;

typedef NS_ENUM(NSInteger, XXZFUpdateErrorCode) {
    XXZFUpdateErrorInvalidManifest = 1,
    XXZFUpdateErrorInvalidSignature = 2,
    XXZFUpdateErrorNoNewerVersion = 3,
    XXZFUpdateErrorNetwork = 4,
    XXZFUpdateErrorPackage = 5,
    XXZFUpdateErrorInstallLocation = 6,
};

static NSError *XXZFUpdateError(XXZFUpdateErrorCode code, NSString *message) {
    return [NSError errorWithDomain:XXZFUpdateErrorDomain
                               code:code
                           userInfo:@{NSLocalizedDescriptionKey: message ?: @"更新校验失败"}];
}

static BOOL XXZFPathHasSymlinkComponent(NSString *path) {
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

static BOOL XXZFIsIntegerNumber(id value) {
    if (![value isKindOfClass:NSNumber.class]
            || CFGetTypeID((__bridge CFTypeRef)value) == CFBooleanGetTypeID()) return NO;
    double number = [value doubleValue];
    return isfinite(number) && floor(number) == number;
}

static BOOL XXZFIsLowercaseHex(NSString *value, NSUInteger length) {
    if (![value isKindOfClass:NSString.class] || value.length != length) return NO;
    NSCharacterSet *allowed = [NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"];
    return [value rangeOfCharacterFromSet:allowed.invertedSet].location == NSNotFound;
}

static NSString *XXZFCanonicalManifest(NSDictionary *manifest) {
    return [@[
        [manifest[@"schema"] stringValue], manifest[@"channel"], manifest[@"platform"],
        [manifest[@"versionCode"] stringValue], manifest[@"version"], manifest[@"url"],
        manifest[@"sha256"], [manifest[@"size"] stringValue], manifest[@"publishedAt"],
        manifest[@"notes"], manifest[@"keyId"]
    ] componentsJoinedByString:@"\n"];
}

static BOOL XXZFVerifyManifestSignature(NSDictionary *manifest) {
    NSData *keyData = [[NSData alloc] initWithBase64EncodedString:XXZFUpdatePublicKey options:0];
    NSData *signature = [[NSData alloc] initWithBase64EncodedString:manifest[@"signature"] options:0];
    NSData *message = [XXZFCanonicalManifest(manifest) dataUsingEncoding:NSUTF8StringEncoding];
    if (!keyData.length || !signature.length || !message.length) return NO;
    NSDictionary *attributes = @{
        (__bridge id)kSecAttrKeyType: (__bridge id)kSecAttrKeyTypeRSA,
        (__bridge id)kSecAttrKeyClass: (__bridge id)kSecAttrKeyClassPublic,
        (__bridge id)kSecAttrKeySizeInBits: @3072
    };
    CFErrorRef createError = NULL;
    SecKeyRef key = SecKeyCreateWithData((__bridge CFDataRef)keyData,
                                         (__bridge CFDictionaryRef)attributes,
                                         &createError);
    if (createError) CFRelease(createError);
    if (!key) return NO;
    CFErrorRef verifyError = NULL;
    BOOL valid = SecKeyVerifySignature(
        key, kSecKeyAlgorithmRSASignatureMessagePKCS1v15SHA256,
        (__bridge CFDataRef)message, (__bridge CFDataRef)signature, &verifyError);
    if (verifyError) CFRelease(verifyError);
    CFRelease(key);
    return valid;
}

static int XXZFRunTask(NSString *launchPath, NSArray<NSString *> *arguments,
                       NSData **standardOutput, NSData **standardError) {
    NSPipe *outputPipe = [NSPipe pipe];
    NSPipe *errorPipe = [NSPipe pipe];
    NSTask *task = [NSTask new];
    task.launchPath = launchPath;
    task.arguments = arguments;
    task.standardOutput = outputPipe;
    task.standardError = errorPipe;
    @try {
        [task launch];
        [task waitUntilExit];
    } @catch (__unused NSException *exception) {
        return -1;
    }
    if (standardOutput) *standardOutput = [outputPipe.fileHandleForReading readDataToEndOfFile];
    if (standardError) *standardError = [errorPipe.fileHandleForReading readDataToEndOfFile];
    return task.terminationStatus;
}

static NSString *XXZFCodeDirectoryHash(NSString *appPath) {
    NSData *details = nil;
    if (XXZFRunTask(@"/usr/bin/codesign", @[@"-d", @"--verbose=4", appPath], nil, &details) != 0
            || !details.length) return nil;
    NSString *text = [[NSString alloc] initWithData:details encoding:NSUTF8StringEncoding];
    for (NSString *line in [text componentsSeparatedByCharactersInSet:NSCharacterSet.newlineCharacterSet]) {
        if ([line hasPrefix:@"CDHash="]) {
            NSString *value = [line substringFromIndex:7];
            return XXZFIsLowercaseHex(value, 40) || XXZFIsLowercaseHex(value, 64) ? value : nil;
        }
    }
    return nil;
}

@interface XXZFNoUpdateRedirectDelegate : NSObject <NSURLSessionTaskDelegate>
@end

@implementation XXZFNoUpdateRedirectDelegate
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
willPerformHTTPRedirection:(NSHTTPURLResponse *)response
        newRequest:(NSURLRequest *)request
 completionHandler:(void (^)(NSURLRequest * _Nullable))completionHandler {
    completionHandler(nil);
}
@end

typedef void (^XXZFDownloadCompletion)(NSString * _Nullable path, NSError * _Nullable error);

@interface XXZFBoundedDownloadDelegate : NSObject <NSURLSessionDownloadDelegate, NSURLSessionTaskDelegate>
@property(nonatomic) unsigned long long expectedSize;
@property(nonatomic, copy) NSString *destination;
@property(nonatomic, copy) XXZFDownloadCompletion completion;
@property(nonatomic) BOOL completed;
@end

@implementation XXZFBoundedDownloadDelegate
- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
willPerformHTTPRedirection:(NSHTTPURLResponse *)response
        newRequest:(NSURLRequest *)request
 completionHandler:(void (^)(NSURLRequest * _Nullable))completionHandler {
    completionHandler(nil);
}

- (void)URLSession:(NSURLSession *)session downloadTask:(NSURLSessionDownloadTask *)downloadTask
      didWriteData:(int64_t)bytesWritten
 totalBytesWritten:(int64_t)totalBytesWritten
totalBytesExpectedToWrite:(int64_t)totalBytesExpectedToWrite {
    if (totalBytesWritten < 0
            || (unsigned long long)totalBytesWritten > self.expectedSize
            || (unsigned long long)totalBytesWritten > XXZFMaximumPackageSize
            || (totalBytesExpectedToWrite > 0
                && (unsigned long long)totalBytesExpectedToWrite != self.expectedSize)) {
        [downloadTask cancel];
    }
}

- (void)URLSession:(NSURLSession *)session downloadTask:(NSURLSessionDownloadTask *)downloadTask
didFinishDownloadingToURL:(NSURL *)location {
    if (self.completed) return;
    NSHTTPURLResponse *response = (NSHTTPURLResponse *)downloadTask.response;
    if (response.statusCode != 200
            || ![response.URL.absoluteString isEqualToString:downloadTask.originalRequest.URL.absoluteString]) {
        self.completed = YES;
        self.completion(nil, XXZFUpdateError(XXZFUpdateErrorNetwork, @"更新下载被重定向或服务器响应异常"));
        return;
    }
    NSFileManager *files = NSFileManager.defaultManager;
    [files removeItemAtPath:self.destination error:nil];
    NSError *moveError = nil;
    if (![files moveItemAtURL:location toURL:[NSURL fileURLWithPath:self.destination] error:&moveError]) {
        self.completed = YES;
        self.completion(nil, XXZFUpdateError(XXZFUpdateErrorPackage, @"无法保存更新文件"));
        return;
    }
    chmod(self.destination.fileSystemRepresentation, 0600);
    self.completed = YES;
    self.completion(self.destination, nil);
}

- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
didCompleteWithError:(NSError *)error {
    if (self.completed) return;
    self.completed = YES;
    self.completion(nil, error ?: XXZFUpdateError(XXZFUpdateErrorNetwork, @"更新下载未完成"));
}
@end

@interface XXZFUpdateManager ()
@property(nonatomic, weak) NSWindow *ownerWindow;
@property(nonatomic) NSInteger currentVersionCode;
@property(nonatomic, copy) NSString *currentVersion;
@property(nonatomic, copy) XXZFUpdateStatusHandler statusHandler;
@property(nonatomic) BOOL checking;
@property(nonatomic, strong) NSURLSession *manifestSession;
@property(nonatomic, strong) NSURLSession *downloadSession;
@property(nonatomic, strong) XXZFBoundedDownloadDelegate *downloadDelegate;
@end

@implementation XXZFUpdateManager

- (instancetype)initWithOwnerWindow:(NSWindow *)window
                  currentVersionCode:(NSInteger)versionCode
                      currentVersion:(NSString *)version
                       statusHandler:(XXZFUpdateStatusHandler)statusHandler {
    self = [super init];
    if (self) {
        _ownerWindow = window;
        _currentVersionCode = versionCode;
        _currentVersion = [version copy];
        _statusHandler = [statusHandler copy];
        NSURLSessionConfiguration *configuration = NSURLSessionConfiguration.ephemeralSessionConfiguration;
        configuration.URLCache = nil;
        configuration.requestCachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
        configuration.timeoutIntervalForRequest = 12;
        configuration.timeoutIntervalForResource = 30;
        _manifestSession = [NSURLSession sessionWithConfiguration:configuration
                                                         delegate:[XXZFNoUpdateRedirectDelegate new]
                                                    delegateQueue:nil];
    }
    return self;
}

- (void)setStatus:(NSString *)status error:(BOOL)isError {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (self.statusHandler) self.statusHandler(status ?: @"", isError);
    });
}

+ (NSDictionary *)validatedManifestFromData:(NSData *)data
                          currentVersionCode:(NSInteger)currentVersionCode
                                       error:(NSError **)error {
    if (!data.length || data.length > XXZFMaximumManifestSize) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorInvalidManifest, @"更新清单大小无效");
        return nil;
    }
    id decoded = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
    if (![decoded isKindOfClass:NSDictionary.class]) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorInvalidManifest, @"更新清单格式无效");
        return nil;
    }
    NSDictionary *manifest = decoded;
    NSSet *expectedKeys = [NSSet setWithArray:@[
        @"schema", @"channel", @"platform", @"versionCode", @"version", @"url",
        @"sha256", @"size", @"publishedAt", @"notes", @"keyId", @"signature"
    ]];
    if (![expectedKeys isEqualToSet:[NSSet setWithArray:manifest.allKeys]]
            || !XXZFIsIntegerNumber(manifest[@"schema"])
            || [manifest[@"schema"] integerValue] != 1
            || ![manifest[@"channel"] isEqual:@"test"]
            || ![manifest[@"platform"] isEqual:@"macos"]
            || !XXZFIsIntegerNumber(manifest[@"versionCode"])
            || !XXZFIsIntegerNumber(manifest[@"size"])
            || ![manifest[@"keyId"] isEqual:XXZFUpdateKeyId]) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorInvalidManifest, @"更新清单字段无效");
        return nil;
    }
    NSString *version = manifest[@"version"];
    NSString *notes = manifest[@"notes"];
    NSString *publishedAt = manifest[@"publishedAt"];
    NSString *signature = manifest[@"signature"];
    NSRange versionMatch = [version isKindOfClass:NSString.class]
        ? [version rangeOfString:@"^[0-9]+\\.[0-9]+\\.[0-9]+$"
                         options:NSRegularExpressionSearch] : NSMakeRange(NSNotFound, 0);
    if (![version isKindOfClass:NSString.class]
            || versionMatch.location != 0 || versionMatch.length != version.length
            || ![manifest[@"url"] isKindOfClass:NSString.class]
            || ![notes isKindOfClass:NSString.class] || notes.length > 1000
            || [notes rangeOfCharacterFromSet:NSCharacterSet.newlineCharacterSet].location != NSNotFound
            || ![publishedAt isKindOfClass:NSString.class] || publishedAt.length > 40
            || ![signature isKindOfClass:NSString.class] || signature.length > 2048
            || !XXZFIsLowercaseHex(manifest[@"sha256"], 64)) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorInvalidManifest, @"更新清单内容无效");
        return nil;
    }
    NSISO8601DateFormatter *formatter = [NSISO8601DateFormatter new];
    if (![formatter dateFromString:publishedAt]) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorInvalidManifest, @"更新发布时间无效");
        return nil;
    }
    long long versionCode = [manifest[@"versionCode"] longLongValue];
    unsigned long long size = [manifest[@"size"] unsignedLongLongValue];
    NSString *expectedURL = [NSString stringWithFormat:@"%@/forwarder-macos-%@-test.dmg",
                             XXZFUpdateBaseURL, version];
    NSURLComponents *components = [NSURLComponents componentsWithString:manifest[@"url"]];
    NSURL *packageURL = [NSURL URLWithString:manifest[@"url"]];
    if (versionCode <= 0 || versionCode > NSIntegerMax
            || size == 0 || size > XXZFMaximumPackageSize
            || ![manifest[@"url"] isEqual:expectedURL]
            || ![components.scheme isEqual:@"https"]
            || ![packageURL.host isEqual:@"updates.example.com"]
            || (components.port && components.port.integerValue != 443)
            || components.user.length || components.password.length
            || components.query.length || components.fragment.length) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorInvalidManifest, @"更新地址或文件大小无效");
        return nil;
    }
    if (!XXZFVerifyManifestSignature(manifest)) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorInvalidSignature, @"更新签名验证失败");
        return nil;
    }
    if (versionCode <= currentVersionCode) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorNoNewerVersion, @"当前已是最新版本");
        return nil;
    }
    return manifest;
}

+ (BOOL)verifyFileAtPath:(NSString *)path expectedSize:(unsigned long long)expectedSize
          expectedSHA256:(NSString *)expectedSHA256 error:(NSError **)error {
    NSDictionary *attributes = [NSFileManager.defaultManager attributesOfItemAtPath:path error:nil];
    if (!attributes || ![[attributes fileType] isEqualToString:NSFileTypeRegular]
            || [attributes fileSize] != expectedSize || expectedSize > XXZFMaximumPackageSize) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorPackage, @"更新文件大小不匹配");
        return NO;
    }
    NSInputStream *stream = [NSInputStream inputStreamWithFileAtPath:path];
    [stream open];
    CC_SHA256_CTX context;
    CC_SHA256_Init(&context);
    uint8_t buffer[64 * 1024];
    NSInteger count = 0;
    while ((count = [stream read:buffer maxLength:sizeof(buffer)]) > 0) {
        CC_SHA256_Update(&context, buffer, (CC_LONG)count);
    }
    [stream close];
    if (count < 0) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorPackage, @"无法读取更新文件");
        return NO;
    }
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256_Final(digest, &context);
    NSMutableString *hex = [NSMutableString stringWithCapacity:64];
    for (NSUInteger index = 0; index < sizeof(digest); index++) {
        [hex appendFormat:@"%02x", digest[index]];
    }
    if (![hex isEqualToString:expectedSHA256]) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorPackage, @"更新文件哈希不匹配");
        return NO;
    }
    return YES;
}

- (void)checkForUpdatesInteractive:(BOOL)interactive {
    if (self.checking) {
        if (interactive) [self setStatus:@"正在检查更新" error:NO];
        return;
    }
    self.checking = YES;
    [self setStatus:@"正在检查更新" error:NO];
    NSMutableURLRequest *request = [NSMutableURLRequest
        requestWithURL:[NSURL URLWithString:XXZFUpdateManifestURL]];
    request.timeoutInterval = 12;
    [request setValue:@"no-store" forHTTPHeaderField:@"Cache-Control"];
    NSURLSessionDataTask *task = [self.manifestSession
        dataTaskWithRequest:request completionHandler:^(NSData *data, NSURLResponse *response, NSError *networkError) {
        self.checking = NO;
        NSHTTPURLResponse *http = (NSHTTPURLResponse *)response;
        if (networkError || http.statusCode != 200
                || ![http.URL.absoluteString isEqualToString:XXZFUpdateManifestURL]
                || data.length > XXZFMaximumManifestSize) {
            [self setStatus:@"检查更新失败" error:YES];
            if (interactive) [self showError:@"无法安全获取更新清单"];
            return;
        }
        NSError *validationError = nil;
        NSDictionary *manifest = [XXZFUpdateManager validatedManifestFromData:data
                                                            currentVersionCode:self.currentVersionCode
                                                                         error:&validationError];
        if (!manifest) {
            if (validationError.code == XXZFUpdateErrorNoNewerVersion) {
                [self setStatus:@"当前已是最新版本" error:NO];
                if (interactive) [self showInformation:@"当前已是最新版本" detail:self.currentVersion];
            } else {
                [self setStatus:@"更新校验失败" error:YES];
                if (interactive) [self showError:validationError.localizedDescription];
            }
            return;
        }
        NSInteger skipped = [NSUserDefaults.standardUserDefaults integerForKey:@"XXZFSkippedUpdateVersionCode"];
        if (!interactive && skipped == [manifest[@"versionCode"] integerValue]) {
            [self setStatus:[NSString stringWithFormat:@"已跳过 %@", manifest[@"version"]] error:NO];
            return;
        }
        dispatch_async(dispatch_get_main_queue(), ^{ [self promptForManifest:manifest]; });
    }];
    [task resume];
}

- (void)promptForManifest:(NSDictionary *)manifest {
    NSAlert *alert = [NSAlert new];
    alert.messageText = [NSString stringWithFormat:@"发现新版本 %@", manifest[@"version"]];
    alert.informativeText = manifest[@"notes"];
    [alert addButtonWithTitle:@"更新"];
    [alert addButtonWithTitle:@"跳过此版本"];
    [alert addButtonWithTitle:@"稍后"];
    [alert beginSheetModalForWindow:self.ownerWindow completionHandler:^(NSModalResponse response) {
        if (response == NSAlertFirstButtonReturn) {
            [self downloadManifest:manifest];
        } else if (response == NSAlertSecondButtonReturn) {
            [NSUserDefaults.standardUserDefaults setInteger:[manifest[@"versionCode"] integerValue]
                                                     forKey:@"XXZFSkippedUpdateVersionCode"];
            [self setStatus:[NSString stringWithFormat:@"已跳过 %@", manifest[@"version"]] error:NO];
        }
    }];
}

- (NSString *)allowedInstallationPath {
    NSString *current = NSBundle.mainBundle.bundlePath.stringByStandardizingPath;
    NSString *system = @"/Applications/转发.app";
    NSString *user = [[NSHomeDirectory() stringByAppendingPathComponent:@"Applications/转发.app"]
        stringByStandardizingPath];
    if (!([current isEqualToString:system] || [current isEqualToString:user])
            || XXZFPathHasSymlinkComponent(current)) return nil;
    return current;
}

- (NSString *)updateDirectory {
    return [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/XXZF/update"];
}

- (void)downloadManifest:(NSDictionary *)manifest {
    NSString *target = [self allowedInstallationPath];
    if (!target.length) {
        [self setStatus:@"请先将“转发”移入应用程序文件夹" error:YES];
        [self showError:@"自动更新只允许替换 /Applications 或个人 Applications 中的“转发.app”"];
        return;
    }
    NSString *directory = [self updateDirectory];
    NSError *directoryError = nil;
    if (XXZFPathHasSymlinkComponent(directory)
            || ![NSFileManager.defaultManager createDirectoryAtPath:directory
                                       withIntermediateDirectories:YES
                                                        attributes:@{NSFilePosixPermissions: @(0700)}
                                                             error:&directoryError]
            || XXZFPathHasSymlinkComponent(directory)) {
        [self setStatus:@"更新目录不安全" error:YES];
        [self showError:@"更新缓存目录包含不受信任的链接"];
        return;
    }
    chmod(directory.fileSystemRepresentation, 0700);
    NSString *destination = [directory stringByAppendingPathComponent:@"forwarder-macos-test.dmg"];
    [self setStatus:@"正在下载安全更新" error:NO];

    XXZFBoundedDownloadDelegate *delegate = [XXZFBoundedDownloadDelegate new];
    delegate.expectedSize = [manifest[@"size"] unsignedLongLongValue];
    delegate.destination = destination;
    __weak typeof(self) weakSelf = self;
    delegate.completion = ^(NSString *path, NSError *downloadError) {
        __strong typeof(weakSelf) self = weakSelf;
        if (!self) return;
        [self.downloadSession finishTasksAndInvalidate];
        self.downloadSession = nil;
        self.downloadDelegate = nil;
        if (downloadError || !path.length) {
            [self setStatus:@"更新下载失败" error:YES];
            [self showError:@"更新下载失败或响应不可信"];
            return;
        }
        NSError *verifyError = nil;
        if (![XXZFUpdateManager verifyFileAtPath:path
                                    expectedSize:[manifest[@"size"] unsignedLongLongValue]
                                  expectedSHA256:manifest[@"sha256"] error:&verifyError]) {
            [NSFileManager.defaultManager removeItemAtPath:path error:nil];
            [self setStatus:@"更新文件校验失败" error:YES];
            [self showError:verifyError.localizedDescription];
            return;
        }
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            NSError *stageError = nil;
            BOOL staged = [self stageDMGAtPath:path manifest:manifest error:&stageError];
            dispatch_async(dispatch_get_main_queue(), ^{
                if (!staged) {
                    [self setStatus:@"更新安装包验证失败" error:YES];
                    [self showError:stageError.localizedDescription];
                    return;
                }
                [self launchUpdateHelperForTarget:target manifest:manifest];
            });
        });
    };
    self.downloadDelegate = delegate;
    NSURLSessionConfiguration *configuration = NSURLSessionConfiguration.ephemeralSessionConfiguration;
    configuration.URLCache = nil;
    configuration.requestCachePolicy = NSURLRequestReloadIgnoringLocalCacheData;
    configuration.timeoutIntervalForRequest = 30;
    configuration.timeoutIntervalForResource = 20 * 60;
    self.downloadSession = [NSURLSession sessionWithConfiguration:configuration delegate:delegate delegateQueue:nil];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:[NSURL URLWithString:manifest[@"url"]]];
    request.timeoutInterval = 30;
    [request setValue:@"no-store" forHTTPHeaderField:@"Cache-Control"];
    [[self.downloadSession downloadTaskWithRequest:request] resume];
}

- (BOOL)stageDMGAtPath:(NSString *)dmg manifest:(NSDictionary *)manifest error:(NSError **)error {
    if (XXZFRunTask(@"/usr/bin/hdiutil", @[@"verify", dmg], nil, nil) != 0) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorPackage, @"DMG 完整性验证失败");
        return NO;
    }
    NSData *plistData = nil;
    if (XXZFRunTask(@"/usr/bin/hdiutil", @[@"attach", @"-plist", @"-readonly", @"-nobrowse", dmg],
                    &plistData, nil) != 0) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorPackage, @"无法以只读方式挂载 DMG");
        return NO;
    }
    NSDictionary *plist = [NSPropertyListSerialization propertyListWithData:plistData
                                                                      options:0 format:nil error:nil];
    NSString *mountPoint = nil;
    for (NSDictionary *entity in plist[@"system-entities"]) {
        NSString *candidate = entity[@"mount-point"];
        if ([candidate isKindOfClass:NSString.class] && [candidate hasPrefix:@"/Volumes/"]) {
            mountPoint = candidate;
            break;
        }
    }
    if (!mountPoint.length) {
        if (error) *error = XXZFUpdateError(XXZFUpdateErrorPackage, @"DMG 挂载点无效");
        return NO;
    }

    BOOL success = NO;
    @try {
        NSString *source = [mountPoint stringByAppendingPathComponent:@"转发.app"];
        NSBundle *bundle = [NSBundle bundleWithPath:source];
        NSDictionary *info = bundle.infoDictionary;
        NSInteger versionCode = [info[@"CFBundleVersion"] integerValue];
        if (XXZFPathHasSymlinkComponent(source)
                || !bundle || ![bundle.bundleIdentifier isEqual:@"com.zundu.xxzf.notifier"]
                || ![info[@"CFBundleShortVersionString"] isEqual:manifest[@"version"]]
                || versionCode != [manifest[@"versionCode"] integerValue]
                || versionCode <= self.currentVersionCode
                || XXZFRunTask(@"/usr/bin/codesign", @[@"--verify", @"--deep", @"--strict", source], nil, nil) != 0) {
            if (error) *error = XXZFUpdateError(XXZFUpdateErrorPackage, @"应用身份、版本或代码签名验证失败");
            return NO;
        }
        NSString *stagedParent = [[self updateDirectory] stringByAppendingPathComponent:@"staged"];
        NSString *staged = [stagedParent stringByAppendingPathComponent:@"转发.app"];
        NSFileManager *files = NSFileManager.defaultManager;
        [files removeItemAtPath:stagedParent error:nil];
        if (![files createDirectoryAtPath:stagedParent withIntermediateDirectories:YES
                               attributes:@{NSFilePosixPermissions: @(0700)} error:error]
                || ![files copyItemAtPath:source toPath:staged error:error]
                || XXZFRunTask(@"/usr/bin/codesign", @[@"--verify", @"--deep", @"--strict", staged], nil, nil) != 0) {
            if (error && !*error) *error = XXZFUpdateError(XXZFUpdateErrorPackage, @"无法安全暂存已验证应用");
            return NO;
        }
        chmod(stagedParent.fileSystemRepresentation, 0700);
        success = YES;
    } @finally {
        XXZFRunTask(@"/usr/bin/hdiutil", @[@"detach", mountPoint], nil, nil);
    }
    return success;
}

- (void)launchUpdateHelperForTarget:(NSString *)target manifest:(NSDictionary *)manifest {
    NSString *bundledHelper = [NSBundle.mainBundle pathForResource:@"XXZFUpdateHelper" ofType:nil];
    NSString *helper = [[self updateDirectory] stringByAppendingPathComponent:@"XXZFUpdateHelper"];
    NSFileManager *files = NSFileManager.defaultManager;
    [files removeItemAtPath:helper error:nil];
    NSError *copyError = nil;
    NSString *staged = [[self updateDirectory] stringByAppendingPathComponent:@"staged/转发.app"];
    NSString *codeDirectoryHash = XXZFCodeDirectoryHash(staged);
    if (!bundledHelper.length || XXZFPathHasSymlinkComponent(bundledHelper)
            || XXZFPathHasSymlinkComponent([self updateDirectory]) || !codeDirectoryHash.length
            || XXZFRunTask(@"/usr/bin/codesign", @[@"--verify", @"--deep", @"--strict", staged], nil, nil) != 0
            || ![files copyItemAtPath:bundledHelper toPath:helper error:&copyError]) {
        [self setStatus:@"无法准备更新程序" error:YES];
        [self showError:@"更新 helper 不可用"];
        return;
    }
    chmod(helper.fileSystemRepresentation, 0700);
    NSTask *task = [NSTask new];
    task.launchPath = helper;
    task.arguments = @[@"--apply", target, manifest[@"version"],
                       [manifest[@"versionCode"] stringValue],
                       codeDirectoryHash,
                       [NSString stringWithFormat:@"%d", getpid()]];
    task.standardOutput = [NSPipe pipe];
    task.standardError = [NSPipe pipe];
    @try {
        [task launch];
        [self setStatus:@"正在安装更新并重新启动" error:NO];
        [NSApp terminate:nil];
    } @catch (__unused NSException *exception) {
        [self setStatus:@"无法启动更新程序" error:YES];
        [self showError:@"更新 helper 启动失败"];
    }
}

- (void)showError:(NSString *)message {
    dispatch_async(dispatch_get_main_queue(), ^{
        NSAlert *alert = [NSAlert new];
        alert.alertStyle = NSAlertStyleWarning;
        alert.messageText = @"更新未安装";
        alert.informativeText = message ?: @"安全验证失败";
        [alert beginSheetModalForWindow:self.ownerWindow completionHandler:nil];
    });
}

- (void)showInformation:(NSString *)message detail:(NSString *)detail {
    dispatch_async(dispatch_get_main_queue(), ^{
        NSAlert *alert = [NSAlert new];
        alert.messageText = message;
        alert.informativeText = detail ?: @"";
        [alert beginSheetModalForWindow:self.ownerWindow completionHandler:nil];
    });
}

@end
