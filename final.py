#!/usr/bin/env python3
"""One-shot deterministic build of com.suji.n1fspeed (Netflix Android TV + speed patch).

State machine:
  1 fresh decompile -> inject setSpeed -> assemble dex
  2 rewrite AXML manifest strings (package/perm/authorities/relative-attr)
  3 byte-faithful zip rebuild (original entries, cert META-INF stripped)
  4 sign + install over previous clone + launch
"""
import os, re, struct, subprocess, sys, zipfile, time

os.chdir("/Users/sujithawijewantha/.t3/scratch/2026-10-23-will-you-hack-into-my-7e6f305e/apk")
APKTOOL_JAR = "/opt/homebrew/Cellar/apktool/3.0.3/libexec/apktool_3.0.3.jar"
MAIN, SPLIT, OUT = "base.apk", "run3-split.apk", "final-base.apk"
TV = "192.168.1.18:5555"

def must(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        print("FAILED:", cmd)
        print(p.stdout[-1500:], p.stderr[-1500:])
        sys.exit(1)
    return p.stdout.strip()

print("[1] fresh decompile")
subprocess.run(["rm", "-rf", "smali_f"], capture_output=True)
must(["apktool", "d", "-f", "-q", MAIN, "-o", "smali_f"])

print("[2] dex injections" + (" (OFF)" if os.environ.get("NO_INJECT") else ""))
def patch(path, subs):
    s = open(path).read()
    for a, b in subs:
        if s.count(a) != 1:
            sys.exit(f"anchor x{s.count(a)} in {path}")
        s = s.replace(a, b)
    open(path, "w").write(s)

PROBE_ON = bool(os.environ.get("PROBE"))
A_WHO = "    invoke-static {p0}, Lcom/suji/Probe;->pwho(Ljava/lang/Object;)V\n" if PROBE_ON else ""
A_RES = ("    move-result v3\n"
         "    invoke-static {v3}, Lcom/suji/Probe;->pspdres(Z)V\n") if PROBE_ON else ""
V_WHO = "    invoke-static {p0}, Lcom/suji/Probe;->pwho(Ljava/lang/Object;)V\n" if PROBE_ON else ""
V_RES = ("    move-result v0\n"
         "    invoke-static {v0}, Lcom/suji/Probe;->pspdres(Z)V\n") if PROBE_ON else ""

if not os.environ.get("NO_INJECT"):
    patch("smali_f/smali/com/netflix/mediaclient/media/JPlayer/MediaDecoder2Audio.smali", [
        (".method unpauseRenderer()V\n    .locals 2",
         ".method unpauseRenderer()V\n    .locals 4"),
        ("    invoke-virtual {v0, v1}, Landroid/os/Handler;->sendEmptyMessage(I)Z\n\n    return-void",
         "    invoke-virtual {v0, v1}, Landroid/os/Handler;->sendEmptyMessage(I)Z\n\n"
         "    # injected: audio clock at 2.0x\n"
         + A_WHO +
         "    new-instance v2, Lcom/netflix/mediaclient/media/JPlayer/PlaySpeed;\n"
         "    const/high16 v3, 0x40000000\n"
         "    invoke-direct {v2, v3}, Lcom/netflix/mediaclient/media/JPlayer/PlaySpeed;-><init>(F)V\n"
         "    invoke-virtual {p0, v2}, Lcom/netflix/mediaclient/media/JPlayer/MediaDecoder2Audio;->setSpeed(Lcom/netflix/mediaclient/media/JPlayer/PlaySpeed;)Z\n"
         + A_RES +
         "    return-void"),
    ])
    patch("smali_f/smali_classes2/com/netflix/mediaclient/media/JPlayer/MediaDecoder2VideoTunneled.smali", [
        ("    invoke-virtual {p1, v0}, Landroid/os/Handler;->sendEmptyMessage(I)Z\n\n    :cond_0\n    return-void\n.end method",
         "    invoke-virtual {p1, v0}, Landroid/os/Handler;->sendEmptyMessage(I)Z\n\n    :cond_0\n"
         "    # injected: secure video decoder keeps up\n"
         + V_WHO +
         "    new-instance p1, Lcom/netflix/mediaclient/media/JPlayer/PlaySpeed;\n"
         "    const/high16 v0, 0x40000000\n"
         "    invoke-direct {p1, v0}, Lcom/netflix/mediaclient/media/JPlayer/PlaySpeed;-><init>(F)V\n"
         "    invoke-virtual {p0, p1}, Lcom/netflix/mediaclient/media/JPlayer/MediaDecoder2VideoTunneled;->setSpeed(Lcom/netflix/mediaclient/media/JPlayer/PlaySpeed;)Z\n"
         + V_RES +
         "    return-void\n.end method"),
    ])
if os.environ.get("PROBE"):
    # log every setSpeed call with its argument, to catch the player resetting to 1.0
    for path, sig in (
        ("smali_f/smali/com/netflix/mediaclient/media/JPlayer/MediaDecoder2Audio.smali",
         ".method public setSpeed(Lcom/netflix/mediaclient/media/JPlayer/PlaySpeed;)Z"),
        ("smali_f/smali_classes2/com/netflix/mediaclient/media/JPlayer/MediaDecoder2VideoTunneled.smali",
         ".method public setSpeed(Lcom/netflix/mediaclient/media/JPlayer/PlaySpeed;)Z"),
    ):
        t = open(path, encoding="utf-8", errors="surrogateescape").read()
        mi = t.index(sig)
        j = t.index("\n", t.index(".locals", mi)) + 1
        ins = ("    invoke-virtual {p1}, Lcom/netflix/mediaclient/media/JPlayer/PlaySpeed;->getSpeed()F\n"
               "    move-result v0\n"
               "    invoke-static {v0}, Lcom/suji/Probe;->pf(F)V\n")
        t = t[:j] + ins + t[j:]
        open(path, "w", encoding="utf-8", errors="surrogateescape").write(t)
if not os.environ.get("NO_INJECT"):
    # Force the speed at the player entry point: Play(float) is what carries the
    # requested speed into mCurSpeed, the master clock and every decoder, so the
    # whole pipeline stays consistent instead of just one decoder going faster.
    JP = "smali_f/smali/com/netflix/mediaclient/media/JPlayer/JPlayer2.smali"
    t = open(JP, encoding="utf-8", errors="surrogateescape").read()
    sig = ".method public Play(F)Z"
    mi = t.index(sig)
    j = t.index("\n", t.index(".locals", mi)) + 1
    ins = ""
    if os.environ.get("PROBE"):
        ins += "    invoke-static {p1}, Lcom/suji/Probe;->pf(F)V\n"
    ins += ("    sput-object p0, Lcom/suji/Speed;->player:Ljava/lang/Object;  # injected: remember live player\n")
    ins += ("    sget p1, Lcom/suji/Speed;->CURRENT:F  # injected: speed from controller\n")
    t = t[:j] + ins + t[j:]
    open(JP, "w", encoding="utf-8", errors="surrogateescape").write(t)
if not os.environ.get("NO_INJECT"):
    # Force the value object: every PlaySpeed instance becomes 2.0x, so nothing
    # downstream (resync, re-configure, reset) can quietly put playback back to 1x.
    PS = "smali_f/smali_classes2/com/netflix/mediaclient/media/JPlayer/PlaySpeed.smali"
    t = open(PS, encoding="utf-8", errors="surrogateescape").read()
    sig = ".method public constructor <init>(F)V"
    mi = t.index(sig)
    j = t.index("\n", t.index(".locals", mi)) + 1
    t = t[:j] + "    sget p1, Lcom/suji/Speed;->CURRENT:F  # injected: speed from controller\n" + t[j:]
    # reset() writes the field directly, bypassing the constructor
    old_reset = (".method public final reset()V\n    .locals 1\n\n"
                 "    const/high16 v0, 0x3f800000    # 1.0f\n")
    new_reset = (".method public final reset()V\n    .locals 1\n\n"
                 "    sget v0, Lcom/suji/Speed;->CURRENT:F    # injected\n")
    if t.count(old_reset) != 1:
        sys.exit("reset() anchor not found")
    t = t.replace(old_reset, new_reset)
    open(PS, "w", encoding="utf-8", errors="surrogateescape").write(t)
if not os.environ.get("NO_INJECT") and os.environ.get("PCM_TRACK"):
    # Open a plain PCM AudioTrack instead of the HW_AV_SYNC/tunnel one: only a mixed
    # PCM track can be time-stretched, which is what playback speed needs.
    MD = "smali_f/smali/com/netflix/mediaclient/media/JPlayer/MediaDecoder2Audio.smali"
    t = open(MD, encoding="utf-8", errors="surrogateescape").read()
    sig = ".method private createAttrAudioTrack(Z)Z"
    mi = t.index(sig)
    j = t.index("\n", t.index(".locals", mi)) + 1
    t = t[:j] + "    const/4 p1, 0x0  # injected: drop FLAG_HW_AV_SYNC\n" + t[j:]
    old = "    iget v7, p0, Lcom/netflix/mediaclient/media/JPlayer/MediaDecoder2Audio;->sidebandSessionId:I\n"
    assert t.count(old) == 1, t.count(old)
    t = t.replace(old, "    const/4 v7, 0x0  # injected: no tunnel audio session\n")
    open(MD, "w", encoding="utf-8", errors="surrogateescape").write(t)
    print("pcm track patch ok")
if not os.environ.get("NO_INJECT"):
    # Netflix clamps playback speed to a device max that its own config reports as 1.0.
    # ConfigVideo stores min(requested, 2.0); force the stored value to the real 2.0 ceiling.
    JP = "smali_f/smali/com/netflix/mediaclient/media/JPlayer/JPlayer2.smali"
    t = open(JP, encoding="utf-8", errors="surrogateescape").read()
    a = "    iput v0, v1, Lcom/netflix/mediaclient/media/JPlayer/JPlayer2;->mMaxSpeed:F\n"
    assert t.count(a) >= 1, t.count(a)
    t = t.replace(a, "    const/high16 v0, 0x40000000  # injected: device max speed 2.0\n" + a, 1)
    open(JP, "w", encoding="utf-8", errors="surrogateescape").write(t)
if not os.environ.get("NO_INJECT") and os.environ.get("NOTUNNEL"):
    # Tunneled video needs a matching tunneled audio session for sync; we removed that
    # to get PCM audio, so the picture stalls. Use the normal render path instead.
    JP = "smali_f/smali/com/netflix/mediaclient/media/JPlayer/JPlayer2.smali"
    t = open(JP, encoding="utf-8", errors="surrogateescape").read()
    a1 = "    iput-boolean v0, v1, Lcom/netflix/mediaclient/media/JPlayer/JPlayer2;->mUseTunneledMode:Z\n"
    a2 = "    iput-boolean v13, v1, Lcom/netflix/mediaclient/media/JPlayer/JPlayer2;->mUseTunneledMode:Z\n"
    assert t.count(a1) == 1 and t.count(a2) == 1
    t = t.replace(a1, "    const/4 v0, 0x0  # injected: non-tunneled video\n" + a1, 1)
    t = t.replace(a2, "    const/4 v13, 0x0  # injected: non-tunneled video\n" + a2, 1)
    open(JP, "w", encoding="utf-8", errors="surrogateescape").write(t)
    print("notunnel patch ok")
if not os.environ.get("NO_INJECT") and os.environ.get("NOZTOP"):
    # Netflix raises the video SurfaceView above the whole window, which hides any
    # in-app overlay. Drop those calls so the surface sits in the normal layer and
    # views drawn by the app (our speed panel) stay on top.
    CL = "smali_f/smali/o/getButtonClickListener.smali"
    t = open(CL, encoding="utf-8", errors="surrogateescape").read()
    a1 = "    invoke-virtual {v0, v5}, Lcom/netflix/mediaclient/android/widget/TappableSurfaceView;->setZOrderOnTop(Z)V\n"
    a2 = "    invoke-virtual {p1, v2}, Landroid/view/SurfaceView;->setZOrderOnTop(Z)V\n"
    for a in (a1, a2):
        assert t.count(a) == 1, (a, t.count(a))
        t = t.replace(a, "    # injected: video surface stays behind the window\n", 1)
    open(CL, "w", encoding="utf-8", errors="surrogateescape").write(t)
    print("noztop patch ok")
if not os.environ.get("NO_INJECT"):
    # give the speed controller the Activity: badge, pause detection, panel
    MA = "smali_f/smali/com/netflix/ninja/MainActivity.smali"
    t = open(MA, encoding="utf-8", errors="surrogateescape").read()
    sig = ".method public onCreate(Landroid/os/Bundle;)V"
    mi = t.index(sig)
    j = t.index("\n", t.index(".locals", mi)) + 1
    t = t[:j] + "    invoke-static {p0}, Lcom/suji/Speed;->attach(Landroid/content/Context;)V  # injected\n" + t[j:]
    open(MA, "w", encoding="utf-8", errors="surrogateescape").write(t)
print("injections ok")


print("[2.4] gibbon null-surface guard" + (" (OFF)" if os.environ.get("NO_GUARD") else ""))
if not os.environ.get("NO_GUARD"): patch("smali_f/smali/com/netflix/ninja/NetflixService.smali", [
    (".method private N(Landroid/view/Surface;Lcom/netflix/ninja/startup/StartupParameters;ZI)V\n    .locals 12\n\n    move-object v8, p0\n\n    move v9, p3",
     ".method private N(Landroid/view/Surface;Lcom/netflix/ninja/startup/StartupParameters;ZI)V\n    .locals 12\n\n"
     "    # injected: hand gibbon a valid dummy Surface when none attached yet\n"
     "    if-nez p1, :cond_gibsurf\n"
     "    new-instance v10, Landroid/graphics/SurfaceTexture;\n"
     "    const/4 v11, 0x0\n"
     "    invoke-direct {v10, v11}, Landroid/graphics/SurfaceTexture;-><init>(I)V\n"
     "    new-instance v11, Landroid/view/Surface;\n"
     "    invoke-direct {v11, v10}, Landroid/view/Surface;-><init>(Landroid/graphics/SurfaceTexture;)V\n"
     "    move-object p1, v11\n"
     "    :cond_gibsurf\n"
     "    move-object v8, p0\n\n    move v9, p3"),
])
print("null-surface guard ok")

print("[2.5] neutralize DexGuard CertCheck")
patch("smali_f/smali/o/setBadgeDrawable$3.smali", [
    (".method public run()V\n    .locals 3",
     ".method public run()V\n    .locals 3\n\n    return-void"),
])

print("[2.6] boot probes" + (" (ON)" if os.environ.get("PROBE") else ""))
if os.environ.get("PROBE"):
    # Probes are zero-argument static helpers: no register pressure at the call site,
    # which matters in methods whose parameters already sit above v15.
    SITES = [
        ("smali_f/smali/com/netflix/ninja/NetflixApplication.smali",
         ".method public onCreate()V", "app.onCreate", "entry"),
        ("smali_f/smali/com/netflix/ninja/MainActivity.smali",
         ".method public onCreate(Landroid/os/Bundle;)V", "activity.onCreate", "entry"),
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         ".method public onCreate()V", "service.onCreate", "entry"),
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         ".method public MHz6Fn06()V", "MHz6Fn06 drm-ready handler", "entry"),
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         ".method private MRiRQ_Ey()V", "MRiRQ_Ey drm-ready branch", "entry"),
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         ".method private N(Landroid/view/Surface;Lcom/netflix/ninja/startup/StartupParameters;ZI)V",
         "gibbonStartup N() enter", "entry"),
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         "    invoke-direct/range {v0 .. v7}, Lcom/netflix/ninja/NetflixService;->nativeGibbonStartup",
         "calling nativeGibbonStartup", "before"),
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         "    .line 2651", "nativeGibbonStartup returned", "before"),
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         ".method private N(Landroid/view/Surface;Lcom/netflix/ninja/startup/StartupParameters;Ljava/lang/String;)V",
         "gibbonResume N() enter", "entry"),
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         ".method public N(I)V", "caller2 N(I)", "entry"),
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         ".method public M135Cu0D(Landroid/view/Surface;Lcom/netflix/ninja/startup/StartupParameters;)V",
         "caller1 M135Cu0D(surface)", "entry"),
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         "    invoke-direct {p0, p1, p2, p3, p4}, Lcom/netflix/ninja/NetflixService;->nativeGibbonPrepare",
         "calling nativeGibbonPrepare", "before"),
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         "    invoke-direct {p0, p1, p2, p3, p4}, Lcom/netflix/ninja/NetflixService;->nativeGibbonPrepare",
         "nativeGibbonPrepare returned", "after"),
    ]

    # Rich probes: inserted verbatim, may use registers that are dead at the site.
    RICH = [
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         ".method private N(Landroid/view/Surface;Lcom/netflix/ninja/startup/StartupParameters;ZI)V",
         "    invoke-direct/range {v0 .. v7}, Lcom/netflix/ninja/NetflixService;->nativeGibbonStartup",
         '    sput-object v2, Lcom/suji/Probe;->s2:Ljava/lang/String;\n'
         '    sput-object v3, Lcom/suji/Probe;->s3:Ljava/lang/String;\n'
         '    sput-object v4, Lcom/suji/Probe;->s4:Ljava/lang/String;\n'
         '    invoke-static {}, Lcom/suji/Probe;->dump()V\n'),
        ("smali_f/smali/com/netflix/ninja/NetflixService.smali",
         ".method private N(Landroid/view/Surface;Lcom/netflix/ninja/startup/StartupParameters;ZI)V",
         "    move-object v8, p0",
         '    const-string v10, "N surface="\n'
         '    invoke-static {v10, p1}, Lcom/suji/Probe;->obj(Ljava/lang/String;Ljava/lang/Object;)V\n'
         '    move-object v11, p1\n'
         '    invoke-virtual {v11}, Landroid/view/Surface;->isValid()Z\n'
         '    move-result v11\n'
         '    const-string v10, "N surface.isValid="\n'
         '    invoke-static {v10, v11}, Lcom/suji/Probe;->zb(Ljava/lang/String;Z)V\n'
         '    const-string v10, "N arg4="\n'
         '    move/from16 v11, p4\n'
         '    invoke-static {v10, v11}, Lcom/suji/Probe;->zi(Ljava/lang/String;I)V\n'
         '    const-string v10, "N arg3="\n'
         '    invoke-static {v10, p3}, Lcom/suji/Probe;->zb(Ljava/lang/String;Z)V\n'),
    ]

    src = ['.class public final Lcom/suji/Probe;', '.super Ljava/lang/Object;', '.source "Probe.java"', '',
           '.field public static s2:Ljava/lang/String;',
           '.field public static s3:Ljava/lang/String;',
           '.field public static s4:Ljava/lang/String;', '']
    for i, (_, _, msg, _) in enumerate(SITES):
        src += [
            f'.method public static p{i}()V',
            '    .locals 2',
            f'    const-string v0, "SUJIDBG"',
            f'    const-string v1, "{i}: {msg}"',
            '    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I',
            '    return-void',
            '.end method',
            '',
        ]
    os.makedirs("smali_f/smali_classes2/com/suji", exist_ok=True)
    open("smali_f/smali_classes2/com/suji/Probe.smali", "w").write("\n".join(src) + """
.method public static obj(Ljava/lang/String;Ljava/lang/Object;)V
    .locals 2
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v0, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p1}, Ljava/lang/StringBuilder;->append(Ljava/lang/Object;)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1
    const-string v0, "SUJIDBG"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public static zi(Ljava/lang/String;I)V
    .locals 2
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v0, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p1}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1
    const-string v0, "SUJIDBG"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public static zb(Ljava/lang/String;Z)V
    .locals 2
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    invoke-virtual {v0, p0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p1}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1
    const-string v0, "SUJIDBG"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public static pf(F)V
    .locals 2
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    const-string v1, "setSpeed called with "
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p0}, Ljava/lang/StringBuilder;->append(F)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1
    const-string v0, "SUJIDBG"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public static pwho(Ljava/lang/Object;)V
    .locals 2
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    const-string v1, "INJECT who="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {p0}, Ljava/lang/Object;->getClass()Ljava/lang/Class;
    move-result-object v1
    invoke-virtual {v1}, Ljava/lang/Class;->getName()Ljava/lang/String;
    move-result-object v1
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1
    const-string v0, "SUJIDBG"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public static pspdres(Z)V
    .locals 2
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    const-string v1, "INJECT setSpeed(2.0) returned "
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0, p0}, Ljava/lang/StringBuilder;->append(Z)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1
    const-string v0, "SUJIDBG"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public static dump()V
    .locals 2
    new-instance v0, Ljava/lang/StringBuilder;
    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V
    const-string v1, "native args save="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    sget-object v1, Lcom/suji/Probe;->s2:Ljava/lang/String;
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    const-string v1, " data="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    sget-object v1, Lcom/suji/Probe;->s3:Ljava/lang/String;
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    const-string v1, " padi="
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    sget-object v1, Lcom/suji/Probe;->s4:Ljava/lang/String;
    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;
    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1
    const-string v0, "SUJIDBG"
    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method
""")

    for i, (path, anchor, msg, where) in enumerate(SITES):
        s = open(path, encoding="utf-8", errors="surrogateescape").read()
        n = s.count(anchor)
        if n != 1:
            sys.exit(f"probe anchor x{n}: {anchor[:60]!r} in {path}")
        ins = f'    invoke-static {{}}, Lcom/suji/Probe;->p{i}()V\n'
        j = s.index(anchor)
        if where == "entry":
            j = s.index("\n", s.index(".locals", j)) + 1
        s = s[:j] + ins + s[j:]
        open(path, "w", encoding="utf-8", errors="surrogateescape").write(s)

    for path, method, anchor, code in RICH:
        s = open(path, encoding="utf-8", errors="surrogateescape").read()
        mi = s.index(method)
        me = s.index(".end method", mi)
        block = s[mi:me]
        if block.count(anchor) != 1:
            sys.exit(f"rich anchor x{block.count(anchor)}: {anchor[:50]!r}")
        block = block.replace(anchor, code + anchor, 1)
        open(path, "w", encoding="utf-8", errors="surrogateescape").write(s[:mi] + block + s[me:])
    print("probes ok")

GLOB = ["smali_f/smali", "smali_f/smali_classes2"]
def perl_swap(pattern, repl):
    for root in GLOB:
        for dp, _, fs in os.walk(root):
            for f in fs:
                if f.endswith(".smali"):
                    p = os.path.join(dp, f)
                    s = open(p, encoding="utf-8", errors="surrogateescape").read()
                    n = s.count(pattern)
                    if n:
                        open(p, "w", encoding="utf-8", errors="surrogateescape").write(s.replace(pattern, repl))
                        return n
    return 0

nn = perl_swap("content://com.netflix.mediaclient.preapp", "content://com.suji.n1fspeed.apppreapp")
print("[3] self-URI swaps:", nn)

print("[3.5] java probe" + (" (ON)" if os.environ.get("PROBE2") else ""))
if os.environ.get("PROBE2"):
    HOME = os.environ["HOME"]
    AJAR = HOME + "/Library/Android/sdk/platforms/android-34/android.jar"
    D8 = HOME + "/Library/Android/sdk/build-tools/36.0.0/d8"
    subprocess.run(["rm", "-rf", "p2out", "p2dex", "classes3.dex"], capture_output=True)
    os.makedirs("p2dex", exist_ok=True)
    SRC = ["../probe2/com/suji/" + f for f in sorted(os.listdir("../probe2/com/suji")) if f.endswith(".java")]
    must(["javac", "--release", "8", "-nowarn", "-cp", AJAR, "-d", "p2out"] + SRC)
    CLASSES = ["p2out/com/suji/" + f for f in sorted(os.listdir("p2out/com/suji")) if f.endswith(".class")]
    must([D8, "--min-api", "24", "--lib", AJAR, "--output", "p2dex"] + CLASSES)
    os.replace("p2dex/classes.dex", "classes3.dex")
    print("classes3.dex:", os.path.getsize("classes3.dex"))
    # call the helpers from NetflixService.onCreate (p0 is the service, a Context)
    SVC = "smali_f/smali/com/netflix/ninja/NetflixService.smali"
    s = open(SVC, encoding="utf-8", errors="surrogateescape").read()
    mi = s.index(".method public onCreate()V")
    j = s.index("\n", s.index(".locals", mi)) + 1
    ins = ("    invoke-static/range {p0 .. p0}, Lcom/suji/Probe2;->pkg(Landroid/content/Context;)V\n"
           "    invoke-static/range {p0 .. p0}, Lcom/suji/Probe2;->query(Landroid/content/Context;)V\n"
           "    invoke-static/range {p0 .. p0}, Lcom/suji/Probe2;->blobs(Landroid/content/Context;)V\n"
           "    invoke-static/range {p0 .. p0}, Lcom/suji/Probe2;->scan(Landroid/content/Context;)V\n")
    open(SVC, "w", encoding="utf-8", errors="surrogateescape").write(s[:j] + ins + s[j:])

if os.environ.get("PROBE2"):
    # measure the real playback rate: the media clock vs wall clock, per clock instance
    CL = "smali_f/smali/com/netflix/mediaclient/media/JPlayer/MediaDecoderBase$Clock.smali"
    t = open(CL, encoding="utf-8", errors="surrogateescape").read()
    a = ".method public updateUs(J)V\n"
    mi = t.index(a)
    j = t.index("\n", t.index(".locals", mi)) + 1
    t = t[:j] + "    invoke-static {p0, p1, p2}, Lcom/suji/Probe2;->tick(Ljava/lang/Object;J)V\n" + t[j:]
    open(CL, "w", encoding="utf-8", errors="surrogateescape").write(t)
print("[4] assemble dex")
subprocess.run(["rm", "-f", "d1.dex", "d2.dex"], capture_output=True)
SCRATCH = "/Users/sujithawijewantha/.t3/scratch/2026-10-23-will-you-hack-into-my-7e6f305e"
CP = SCRATCH + "/smali252.jar:" + ":".join(SCRATCH + "/cp/" + f for f in os.listdir(SCRATCH + "/cp") if f.endswith(".jar"))
must(["java", "-cp", CP, "org.jf.smali.Main", "assemble", "-o", "d1.dex", "smali_f/smali"])
must(["java", "-cp", CP, "org.jf.smali.Main", "assemble", "-o", "d2.dex", "smali_f/smali_classes2"])
print("d1:", os.path.getsize("d1.dex"), "d2:", os.path.getsize("d2.dex"))

print("[5] AXML rewrite")
LABEL_STATE = {"idx": None, "name_idx": None}

def process_pool(chunk):
    cty, chsz, size = struct.unpack_from("<HHI", chunk, 0)
    cnt, scnt, flags, sstart, _ = struct.unpack_from("<IIIII", chunk, 8)
    utf8 = bool(flags & (1 << 8))
    strs = []
    for i in range(cnt):
        p = sstart + struct.unpack_from("<I", chunk, 28 + 4*i)[0]
        if utf8:
            def rv(pos, ch=chunk):
                b = ch[pos]
                return (((b & 0x7F) << 8) | ch[pos+1], pos+2) if b & 0x80 else (b, pos+1)
            _, p2 = rv(p); n8, p3 = rv(p2)
            strs.append(chunk[p3:p3+n8].decode("utf-8"))
        else:
            nw = struct.unpack_from("<H", chunk, p)[0]
            if nw & 0x8000:
                nw = ((nw & 0x7FFF) << 16) | struct.unpack_from("<H", chunk, p+2)[0]
                body = p + 4
            else:
                body = p + 2
            strs.append(chunk[body:body+nw*2].decode("utf-16-le"))

    mk = lambda h, t, n: h + "a" * (n - len(h) - len(t)) + t
    NPM = "com.suji.n1fspeed"
    NEW_PREAPP = mk("com.suji.n1fspeed.", "apppreapp", len("com.netflix.mediaclient.preapp"))
    OLD_MG = "com.netflix.partner.contentprovider.permission.MODEL_GROUP"
    NEW_MG = mk("com.suji.n1fspeed.", "partner.contentprovider.permission.MODEL_GROUP", len(OLD_MG))

    dot_like = [s for s in strs if re.fullmatch(r"\.[A-Za-z][\w$.]*", s)]
    print("relative-to-absolutize:", dot_like)

    changes = []
    for i, s in enumerate(strs):
        o = s
        if s == "com.netflix.ninja":
            s = NPM
        elif s.startswith("com.netflix.ninja.permission."):
            s = s.replace("com.netflix.ninja", NPM, 1)
        elif s == OLD_MG:
            s = NEW_MG
        elif s.endswith("DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION"):
            s = s.replace("com.netflix.ninja", NPM, 1)
        elif s in ("com.netflix.ninja.androidx-startup", "com.netflix.ninja.bugsnag-startup", "com.netflix.ninja.firebaseinitprovider"):
            s = s.replace("com.netflix.ninja", NPM, 1)
        elif s == "com.netflix.mediaclient.preapp":
            s = NEW_PREAPP
        elif s in dot_like:
            s = "com.netflix.ninja" + s
        elif os.environ.get("QUERY_GRANT") and s == "com.google.android.katniss":
            # package-visibility grant for the official package: the native boot
            # asks the PackageManager about com.netflix.ninja and aborts when the
            # lookup is blocked. This <queries> slot is the cheapest place to put it.
            s = "com.netflix.ninja"
        if s != o:
            changes.append((i, o, s))
            strs[i] = s
    for i, o, s in changes:
        print(f"  str[{i}]: {o[:60]!r} -> {s[:60]!r}")

    if os.environ.get("MERGE"):
        for i, val in enumerate(strs):
            if val == "base__abi":
                strs[i] = ""

    if os.environ.get("LABEL"):
        try:
            LABEL_STATE["name_idx"] = strs.index("label")
        except ValueError:
            LABEL_STATE["name_idx"] = None
        LABEL_STATE["idx"] = len(strs)
        strs.append(os.environ["LABEL"])

    blob = bytearray(); offs = []
    for s in strs:
        offs.append(len(blob))
        if utf8:
            def v(n):
                return bytes([n]) if n < 0x80 else bytes([(n >> 8) | 0x80, n & 0xFF])
            u = len(s.encode("utf-16-le")); e = s.encode("utf-8")
            blob += v(u) + v(len(e)) + e + b"\x00"
        else:
            blob += struct.pack("<H", len(s)) + s.encode("utf-16-le") + b"\x00\x00"
    if len(blob) % 4:
        blob += b"\x00" * (4 - len(blob) % 4)
    sstart2 = 28 + 4 * cnt
    total = sstart2 + len(blob)
    head = struct.pack("<HHIIIIII", 0x0001, chsz, total, cnt, scnt, flags, sstart2, 0)
    head += b"".join(struct.pack("<I", o) for o in offs)
    return bytes(head) + bytes(blob)

def patch_label(b):
    """Repoint the <application android:label> attribute at our literal string."""
    t, h, total = struct.unpack_from("<HHI", b, 0)
    pos = h
    app_name = None
    pool = None
    while pos < total:
        ct, chsz, csz = struct.unpack_from("<HHI", b, pos)
        chunk = b[pos:pos+csz]
        if ct == 0x0001 and pool is None:
            pool = parse_pool_strings(chunk)
            try:
                app_name = pool.index("application")
            except ValueError:
                app_name = None
        if ct == 0x0102 and app_name is not None:
            ns, name = struct.unpack_from("<II", b, pos + 16)
            if name == app_name:
                attr_start, attr_size, attr_count = struct.unpack_from("<HHH", b, pos + 24)
                ap = pos + 16 + attr_start
                for i in range(attr_count):
                    off = ap + i * 20
                    ns_i, name_i, raw_i = struct.unpack_from("<III", b, off)
                    if name_i == LABEL_STATE["name_idx"]:
                        struct.pack_into("<I", b, off + 8, LABEL_STATE["idx"])
                        struct.pack_into("<HBB", b, off + 12, 8, 0, 0x03)
                        struct.pack_into("<I", b, off + 16, LABEL_STATE["idx"])
                        print("label attr repointed ->", os.environ.get("LABEL"))
                        return b
        pos += csz
    print("label attr not found")
    return b

def parse_pool_strings(chunk):
    cnt, scnt, flags, sstart, _ = struct.unpack_from("<IIIII", chunk, 8)
    utf8 = bool(flags & (1 << 8))
    out = []
    for i in range(cnt):
        p = sstart + struct.unpack_from("<I", chunk, 28 + 4 * i)[0]
        if utf8:
            def rv(pos):
                x = chunk[pos]
                return (((x & 0x7F) << 8) | chunk[pos + 1], pos + 2) if x & 0x80 else (x, pos + 1)
            _, p2 = rv(p); n8, p3 = rv(p2)
            out.append(chunk[p3:p3 + n8].decode("utf-8", "replace"))
        else:
            nw = struct.unpack_from("<H", chunk, p)[0]
            if nw & 0x8000:
                nw = ((nw & 0x7FFF) << 16) | struct.unpack_from("<H", chunk, p + 2)[0]; body = p + 4
            else:
                body = p + 2
            out.append(chunk[body:body + nw * 2].decode("utf-16-le", "replace"))
    return out

def rewrite_axml(src):
    t, h, s = struct.unpack_from("<HHI", src, 0)
    out = bytearray(src[:h]); pos = h
    while pos < s:
        ct, chsz, csz = struct.unpack_from("<HHI", src, pos)
        c = src[pos:pos+csz]
        if ct == 0x0001:
            print("pool chunk at", hex(pos), "size", csz)
            c = process_pool(c)
        out += c
        pos += csz
    struct.pack_into("<HHI", out, 0, t, h, len(out))
    return bytes(out)

z = zipfile.ZipFile(MAIN)
axml2 = rewrite_axml(z.read("AndroidManifest.xml"))
if os.environ.get("LABEL") and LABEL_STATE["idx"] is not None:
    axml2 = patch_label(bytearray(axml2))
print("axml:", len(z.read('AndroidManifest.xml')), "->", len(axml2))

print("[6] zip rebuild")
out = zipfile.ZipFile(OUT, "w")
for info in z.infolist():
    leaf = info.filename.rsplit(".", 1)[-1].upper()
    if info.filename.startswith("META-INF/") and (leaf in ("SF","RSA","DSA","EC") or info.filename.endswith("MANIFEST.MF")):
        continue
    data = z.read(info.filename)
    if info.filename == "AndroidManifest.xml":
        data = axml2
    elif info.filename == "classes.dex":
        data = open("d1.dex","rb").read()
    elif info.filename == "classes2.dex":
        data = open("d2.dex","rb").read()
    if os.environ.get("ICON") and ("/ic_launcher.png" in info.filename or "/ic_banner.png" in info.filename):
        custom = "icons/" + info.filename.replace("/", "_")
        if os.path.exists(custom):
            data = open(custom, "rb").read()
    zi = zipfile.ZipInfo(info.filename, info.date_time)
    zi.compress_type = info.compress_type
    zi.external_attr = info.external_attr
    zi.create_system = info.create_system
    out.writestr(zi, data)
if os.environ.get("PROBE2"):
    out.writestr("classes3.dex", open("classes3.dex", "rb").read())
out.close()
z.close()
print(OUT, os.path.getsize(OUT))

print("[6.5] split rebuild: retarget native getPackageInfo to our package")
OLD = b"com.netflix.ninja"
NEW = b"com.suji.n1fspeed"
assert len(OLD) == len(NEW)
zsplit = zipfile.ZipFile(SPLIT)
so = zsplit.read("lib/armeabi-v7a/libnetflix.so")
before = so.count(OLD)
if os.environ.get("KEEP_PKGSTR"):
    print("libnetflix.so package-string: LEFT AS com.netflix.ninja (official pkg is installed)")
else:
    so = so.replace(OLD, NEW)
    print("libnetflix.so package-string swap hits:", before)
    assert before == 1
out2 = zipfile.ZipFile("final-split.apk", "w")
for info in zsplit.infolist():
    leaf = info.filename.rsplit(".", 1)[-1].upper()
    if info.filename.startswith("META-INF/") and (leaf in ("SF","RSA","DSA","EC") or info.filename.endswith("MANIFEST.MF")):
        continue
    data = zsplit.read(info.filename)
    if info.filename == "lib/armeabi-v7a/libnetflix.so":
        data = so
    zi = zipfile.ZipInfo(info.filename, info.date_time)
    zi.compress_type = info.compress_type
    zi.external_attr = info.external_attr
    zi.create_system = info.create_system
    out2.writestr(zi, data)
out2.close()
zsplit.close()
must(["java","-jar","uber.jar","--apks","final-split.apk","--ks","tv.keystore","--ksAlias","tv",
      "--ksPass","netf1ix","--ksKeyPass","netf1ix","--overwrite"])
print("final-split.apk signed", os.path.getsize("final-split.apk"))

print("[7] sign")
must(["java","-jar","uber.jar","--apks",OUT,"--ks","tv.keystore","--ksAlias","tv",
      "--ksPass","netf1ix","--ksKeyPass","netf1ix","--overwrite"])

if os.environ.get("MERGE"):
    print("[7.5] merged standalone apk")
    zb = zipfile.ZipFile(OUT)
    zs = zipfile.ZipFile("final-split.apk")
    merged = "netflix2x-merged.apk"
    outm = zipfile.ZipFile(merged, "w")
    for info in zb.infolist():
        leaf = info.filename.rsplit(".", 1)[-1].upper()
        if info.filename.startswith("META-INF/") and (leaf in ("SF","RSA","DSA","EC") or info.filename.endswith("MANIFEST.MF")):
            continue
        zi = zipfile.ZipInfo(info.filename, info.date_time)
        zi.compress_type = info.compress_type
        zi.external_attr = info.external_attr
        zi.create_system = info.create_system
        outm.writestr(zi, zb.read(info.filename))
    for info in zs.infolist():
        if not info.filename.startswith("lib/"):
            continue
        zi = zipfile.ZipInfo(info.filename, info.date_time)
        zi.compress_type = info.compress_type
        zi.external_attr = info.external_attr
        zi.create_system = info.create_system
        outm.writestr(zi, zs.read(info.filename))
    outm.close(); zb.close(); zs.close()
    must(["java","-jar","uber.jar","--apks",merged,"--ks","tv.keystore","--ksAlias","tv",
          "--ksPass","netf1ix","--ksKeyPass","netf1ix","--overwrite"])
    print("merged:", os.path.getsize(merged))

print("[8] install")
p = subprocess.run(["adb","-s",TV,"install-multiple",OUT,"final-split.apk"], capture_output=True, text=True)
print(p.stdout.strip(), p.stderr.strip())
if "Success" not in (p.stdout + p.stderr):
    sys.exit(1)

print("[9] launch")
subprocess.run(["adb","-s",TV,"shell","logcat","-c"], capture_output=True)
lp = subprocess.run(["adb","-s",TV,"shell","monkey","-p","com.suji.n1fspeed",
                     "-c","android.intent.category.LEANBACK_LAUNCHER","1"],
                    capture_output=True, text=True)
print("monkey:", lp.stdout.strip()[-80:] or "started")
time.sleep(15)
ps = subprocess.run(["adb","-s",TV,"shell","ps","-A"], capture_output=True, text=True).stdout
print("process:", "ALIVE" if "suji" in ps else "NOT RUNNING")
crash = subprocess.run(["adb","-s",TV,"logcat","-b","crash","-d"],
                       capture_output=True, text=True).stdout
tail = crash.strip().splitlines()[-14:]
print("\n".join(tail))
