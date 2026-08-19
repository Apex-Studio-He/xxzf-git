#import <Cocoa/Cocoa.h>

NS_ASSUME_NONNULL_BEGIN

typedef void (^XXZFUpdateStatusHandler)(NSString *status, BOOL isError);

@interface XXZFUpdateManager : NSObject

- (instancetype)initWithOwnerWindow:(nullable NSWindow *)window
                  currentVersionCode:(NSInteger)versionCode
                      currentVersion:(NSString *)version
                       statusHandler:(XXZFUpdateStatusHandler)statusHandler;

- (void)checkForUpdatesInteractive:(BOOL)interactive;

+ (nullable NSDictionary *)validatedManifestFromData:(NSData *)data
                                   currentVersionCode:(NSInteger)currentVersionCode
                                                error:(NSError **)error;
+ (BOOL)verifyFileAtPath:(NSString *)path
            expectedSize:(unsigned long long)expectedSize
          expectedSHA256:(NSString *)expectedSHA256
                   error:(NSError **)error;

@end

NS_ASSUME_NONNULL_END
