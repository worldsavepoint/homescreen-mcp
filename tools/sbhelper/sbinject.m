// Loaded into the Simulator's SpringBoard (DYLD_INSERT_LIBRARIES). On the Darwin
// notification "homescreen.import" it reads $SBTEST_DIR/in.plist and calls
// [[SBApp defaultIconController] importIconState:] -- what SpringBoard's
// SBXXSetIconState handler does for a USB setIconState request -- skipping only the
// entitlement check. The result goes to $SBTEST_DIR/out.txt.
#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>
#import <objc/message.h>
#include <notify.h>

// On "homescreen.export", converts $SBTEST_DIR/archive.plist (SpringBoard's on-disk form) to the
// list form a USB getIconState returns, via +[SBIconStateArchiver iTunesRepresentationFromRootArchive:...],
// and writes it to $SBTEST_DIR/itunes.plist.
static void sbinject_export(NSString *dir) {
    NSData *d = [NSData dataWithContentsOfFile:[dir stringByAppendingPathComponent:@"archive.plist"]];
    id archive = d ? [NSPropertyListSerialization propertyListWithData:d options:0 format:NULL error:NULL] : nil;
    Class cls = NSClassFromString(@"SBIconStateArchiver");
    SEL sel = sel_registerName("iTunesRepresentationFromRootArchive:preApex:pending:iconSource:");
    NSString *res;
    @try {
        id rep = ((id (*)(id, SEL, id, BOOL, BOOL, id))objc_msgSend)(cls, sel, archive, NO, NO, nil);
        NSData *out = [NSPropertyListSerialization dataWithPropertyList:rep format:NSPropertyListXMLFormat_v1_0 options:0 error:NULL];
        [out writeToFile:[dir stringByAppendingPathComponent:@"itunes.plist"] atomically:YES];
        res = [NSString stringWithFormat:@"export ok=%d class=%@\n", out != nil, NSStringFromClass([rep class])];
    } @catch (NSException *e) {
        res = [NSString stringWithFormat:@"export err=%@\n", e.description];
    }
    [res writeToFile:[dir stringByAppendingPathComponent:@"out.txt"] atomically:YES encoding:NSUTF8StringEncoding error:NULL];
}

#import <objc/runtime.h>

static id call0(id o, const char *sel) {
    if (!o) return nil;
    SEL s = sel_registerName(sel);
    @try { return ((id (*)(id, SEL))objc_msgSend)(o, s); } @catch (NSException *e) { return nil; }
}

static id icon_controller(void) {
    id app = UIApplication.sharedApplication;
    if ([app respondsToSelector:sel_registerName("defaultIconController")])
        return call0(app, "defaultIconController");
    return call0(NSClassFromString(@"SBIconController"), "sharedInstance");
}

// On "homescreen.gap": pin $SBTEST_DIR/gap.txt's bundle id ("bundle cellIndex") to a grid cell
// on page 1 through -[SBIconListModel addFixedIconLocations:options:], save, and log what it did.
static void sbinject_gap(NSString *dir) {
    NSMutableString *log = [NSMutableString string];
    @try {
        NSArray *args = [[NSString stringWithContentsOfFile:[dir stringByAppendingPathComponent:@"gap.txt"]
                                                    encoding:NSUTF8StringEncoding error:NULL] componentsSeparatedByString:@" "];
        NSString *bundle = args[0];
        NSInteger cell = [args[1] integerValue];
        id ctl = icon_controller();
        id model = call0(ctl, "iconModel");
        id root = call0(model, "rootFolder");
        NSArray *lists = call0(root, "lists");
        id list = lists.firstObject;
        [log appendFormat:@"list=%@ fixed(before)=%@\n", NSStringFromClass([list class]), call0(list, "fixedIconLocations")];
        Method m = class_getInstanceMethod([list class], sel_registerName("addFixedIconLocations:options:"));
        [log appendFormat:@"addFixedIconLocations types=%s\n", m ? method_getTypeEncoding(m) : "none"];
        id icon = nil;
        for (id i in (NSArray *)call0(list, "icons")) {
            if ([[call0(i, "applicationBundleID") description] isEqual:bundle] || [[call0(i, "leafIdentifier") description] isEqual:bundle]) icon = i;
        }
        [log appendFormat:@"icon=%@\n", icon];
        NSString *mode = args.count > 2 ? args[2] : @"icon";
        id key = [mode isEqual:@"id"] ? (id)bundle : icon;
        NSDictionary *locs = @{key: @(cell)};
        ((void (*)(id, SEL, id, NSUInteger))objc_msgSend)(list, sel_registerName("addFixedIconLocations:options:"), locs, 0);
        [log appendFormat:@"fixed(after)=%@\n", call0(list, "fixedIconLocations")];
        for (const char *sv : (const char *[]){"saveIconStateIfNeeded", "saveIconState", "markIconStateDirty"}) {
            SEL s = sel_registerName(sv);
            if ([model respondsToSelector:s]) { ((void (*)(id, SEL))objc_msgSend)(model, s); [log appendFormat:@"called %s\n", sv]; }
        }
    } @catch (NSException *e) {
        [log appendFormat:@"error: %@\n", e];
    }
    [log writeToFile:[dir stringByAppendingPathComponent:@"out.txt"] atomically:YES encoding:NSUTF8StringEncoding error:NULL];
}

// On "homescreen.exports": write what SpringBoard's two icon-state exports return (the ones
// behind SBGetIconState and SBGetFlattenedIconState) to $SBTEST_DIR/export-*.plist.
static void sbinject_exports(NSString *dir) {
    NSMutableString *log = [NSMutableString string];
    id ctl = icon_controller();
    id model = call0(ctl, "iconModel");
    [log appendFormat:@"app=%@ ctl=%@ model=%@\n", NSStringFromClass([UIApplication.sharedApplication class]), NSStringFromClass([ctl class]), NSStringFromClass([model class])];
    void (^save)(NSString *, id) = ^(NSString *name, id obj) {
        NSData *d = obj ? [NSPropertyListSerialization dataWithPropertyList:obj format:NSPropertyListXMLFormat_v1_0 options:0 error:NULL] : nil;
        [d writeToFile:[dir stringByAppendingPathComponent:name] atomically:YES];
        [log appendFormat:@"%@: %@ %lu bytes\n", name, NSStringFromClass([obj class]), (unsigned long)d.length];
    };
    @try {
        for (int flag = 0; flag < 2; flag++)
            save([NSString stringWithFormat:@"export-state-%d.plist", flag],
                 ((id (*)(id, SEL, BOOL))objc_msgSend)(model, sel_registerName("exportState:"), flag));
        for (int a = 0; a < 2; a++) for (int b = 0; b < 2; b++)
            save([NSString stringWithFormat:@"export-pending-%d%d.plist", a, b],
                 ((id (*)(id, SEL, BOOL, BOOL))objc_msgSend)(model, sel_registerName("exportPendingState:includeMissingIcons:"), a, b));
        for (int a = 0; a < 2; a++) for (int b = 0; b < 2; b++)
            save([NSString stringWithFormat:@"export-flat-%d%d.plist", a, b],
                 ((id (*)(id, SEL, BOOL, BOOL))objc_msgSend)(model, sel_registerName("exportFlattenedState:includeMissingIcons:"), a, b));
    } @catch (NSException *e) { [log appendFormat:@"error %@\n", e]; }
    [log writeToFile:[dir stringByAppendingPathComponent:@"out.txt"] atomically:YES encoding:NSUTF8StringEncoding error:NULL];
}

__attribute__((constructor)) static void sbinject_init(void) {
    NSString *dir = NSProcessInfo.processInfo.environment[@"SBTEST_DIR"] ?: @"/tmp";
    static int token, token2, token3, token4;
    notify_register_dispatch("homescreen.exports", &token4, dispatch_get_main_queue(), ^(int t) { sbinject_exports(dir); });
    notify_register_dispatch("homescreen.gap", &token3, dispatch_get_main_queue(), ^(int t) { sbinject_gap(dir); });
    notify_register_dispatch("homescreen.export", &token2, dispatch_get_main_queue(), ^(int t) { sbinject_export(dir); });
    notify_register_dispatch("homescreen.import", &token, dispatch_get_main_queue(), ^(int t) {
        NSData *d = [NSData dataWithContentsOfFile:[dir stringByAppendingPathComponent:@"in.plist"]];
        id plist = d ? [NSPropertyListSerialization propertyListWithData:d options:0 format:NULL error:NULL] : nil;
        BOOL ok = NO;
        NSString *err = @"";
        @try {
            id ctl = icon_controller();
            ok = ((BOOL (*)(id, SEL, id))objc_msgSend)(ctl, sel_registerName("importIconState:"), plist);
        } @catch (NSException *e) {
            err = e.description;
        }
        NSString *res = [NSString stringWithFormat:@"ok=%d input=%@ err=%@\n", ok, NSStringFromClass([plist class]), err];
        [res writeToFile:[dir stringByAppendingPathComponent:@"out.txt"] atomically:YES encoding:NSUTF8StringEncoding error:NULL];
    });
}
