// Read an installed simulator app's rendered icon, including asset-catalog icons.
#import <UIKit/UIKit.h>
#import <objc/message.h>
#include <stdio.h>

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 2) return 2;
        SEL selector = sel_registerName("_applicationIconImageForBundleIdentifier:format:scale:");
        if (![UIImage respondsToSelector:selector]) return 3;
        @try {
            UIImage *image = ((id (*)(id, SEL, id, int, CGFloat))objc_msgSend)(
                [UIImage class], selector, [NSString stringWithUTF8String:argv[1]], 2, 2.0);
            NSData *png = image ? UIImagePNGRepresentation(image) : nil;
            if (!png) return 4;
            return fwrite(png.bytes, 1, png.length, stdout) == png.length ? 0 : 5;
        } @catch (NSException *exception) {
            return 6;
        }
    }
}
