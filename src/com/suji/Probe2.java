package com.suji;

import android.content.Context;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;

/** Read-only introspection helpers injected into the cloned Netflix process. */
public final class Probe2 {
    private static final String TAG = "SUJIDBG";

    private Probe2() {}

    /** List the app's private data tree and tail any log-like files. */
    public static void dump(Context ctx) {
        try {
            File root = ctx.getFilesDir().getParentFile();
            walk(root, 0);
        } catch (Throwable t) {
            Log.i(TAG, "dump failed: " + t);
        }
    }

    private static void walk(File f, int depth) {
        if (depth > 5) {
            return;
        }
        File[] kids = f.listFiles();
        if (kids == null) {
            return;
        }
        for (File k : kids) {
            if (k.isDirectory()) {
                walk(k, depth + 1);
            } else {
                Log.i(TAG, "FILE " + k.getAbsolutePath() + " " + k.length());
            }
        }
    }

    /** Log every Netflix diagnostic log blob in full (they are tiny). */
    public static void blobs(Context ctx) {
        try {
            File dir = new File(ctx.getFilesDir(), "logblobs");
            dumpAll(dir, 0);
        } catch (Throwable t) {
            Log.i(TAG, "blobs failed: " + t);
        }
    }

    private static void dumpAll(File f, int depth) {
        if (depth > 4) {
            return;
        }
        File[] kids = f.listFiles();
        if (kids == null) {
            return;
        }
        for (File k : kids) {
            if (k.isDirectory()) {
                dumpAll(k, depth + 1);
            } else if (k.length() > 0 && k.length() < 100_000) {
                InputStream in = null;
                try {
                    in = new FileInputStream(k);
                    byte[] b = new byte[(int) k.length()];
                    int n = in.read(b);
                    String s = new String(b, 0, Math.max(n, 0), "UTF-8");
                    if (s.indexOf('\0') >= 0) {
                        for (String run : printableRuns(b, Math.max(n, 0))) {
                            Log.i(TAG, "BLOB " + k.getName() + "| " + trim(run));
                        }
                    } else {
                        for (String line : s.split("\n")) {
                            if (!line.trim().isEmpty()) {
                                Log.i(TAG, "BLOB " + k.getName() + "| " + trim(line));
                            }
                        }
                    }
                } catch (Throwable t) {
                    Log.i(TAG, "blob err " + k + ": " + t);
                } finally {
                    if (in != null) {
                        try {
                            in.close();
                        } catch (Throwable ignored) {
                        }
                    }
                }
            }
        }
    }


    private static final java.util.HashMap<Integer, long[]> TICKS = new java.util.HashMap<>();

    /** Called from the playback clock: logs media time vs wall clock, per clock instance. */
    public static void tick(Object clock, long ptsUs) {
        try {
            long wall = android.os.SystemClock.elapsedRealtime();
            int id = System.identityHashCode(clock);
            long[] prev = TICKS.get(id);
            if (prev != null && wall - prev[0] < 1000L) {
                return;
            }
            if (prev != null && prev[0] > 0 && wall > prev[0]) {
                double rate = (double) (ptsUs - prev[1]) / (double) ((wall - prev[0]) * 1000L);
                Log.i(TAG, "RATE clock=" + id + " rate=" + String.format("%.3f", rate)
                        + " ptsMs=" + (ptsUs / 1000L) + " wallMs=" + wall);
            } else {
                Log.i(TAG, "RATE start clock=" + id + " ptsMs=" + (ptsUs / 1000L));
            }
            TICKS.put(id, new long[]{wall, ptsUs});
        } catch (Throwable ignored) {
        }
    }

    /** Dump the app's own package signature + installer, as the native layer would see it. */
    public static void pkg(Context ctx) {
        try {
            android.content.pm.PackageManager pm = ctx.getPackageManager();
            android.content.pm.PackageInfo pi =
                    pm.getPackageInfo(ctx.getPackageName(), android.content.pm.PackageManager.GET_SIGNATURES);
            StringBuilder sb = new StringBuilder("PKG " + pi.packageName + " v" + pi.versionName);
            sb.append(" sigs=").append(pi.signatures == null ? "null" : pi.signatures.length);
            if (pi.signatures != null) {
                for (android.content.pm.Signature s : pi.signatures) {
                    sb.append(" hash=").append(s.hashCode()).append(" chars=").append(s.toCharsString().length());
                }
            }
            sb.append(" installer=").append(pm.getInstallerPackageName(pi.packageName));
            Log.i(TAG, sb.toString());
        } catch (Throwable t) {
            Log.i(TAG, "pkg failed: " + t);
        }
    }

    /** Query the *official* package the way the native boot does, and report what happens. */
    public static void query(Context ctx) {
        try {
            android.content.pm.PackageManager pm = ctx.getPackageManager();
            android.content.pm.PackageInfo pi =
                    pm.getPackageInfo("com.netflix.ninja", android.content.pm.PackageManager.GET_SIGNATURES);
            StringBuilder sb = new StringBuilder("QUERY ok " + pi.packageName + " v" + pi.versionName
                    + " sigs=" + (pi.signatures == null ? "null" : pi.signatures.length));
            if (pi.signatures != null) {
                for (android.content.pm.Signature s : pi.signatures) {
                    sb.append(" hash=").append(s.hashCode());
                }
            }
            Log.i(TAG, sb.toString());
        } catch (Throwable t) {
            Log.i(TAG, "QUERY failed: " + t);
        }
    }

    /** Scan small text-ish files under the data dir for startup keywords and log the hits. */
    public static void scan(Context ctx) {
        try {
            File root = ctx.getFilesDir().getParentFile();
            walkScan(root, 0, 0);
        } catch (Throwable t) {
            Log.i(TAG, "scan failed: " + t);
        }
    }

    private static final String[] KEYS = {
        "gibbon", "nrdp", "cert", "signature", "tamper", "boot", "padi", "license", "validation"
    };

    private static void walkScan(File f, int depth, int budget) {
        if (depth > 5) {
            return;
        }
        File[] kids = f.listFiles();
        if (kids == null) {
            return;
        }
        for (File k : kids) {
            if (k.isDirectory()) {
                walkScan(k, depth + 1, budget);
            } else if (k.length() > 0 && k.length() < 400_000) {
                scanFile(k);
            }
        }
    }

    private static void scanFile(File f) {
        InputStream in = null;
        int hits = 0;
        try {
            in = new FileInputStream(f);
            byte[] b = new byte[(int) Math.min(f.length(), 400_000)];
            int n = in.read(b);
            if (n <= 0) {
                return;
            }
            String s = new String(b, 0, n, "UTF-8");
            String[] lines = s.split("\n");
            for (String line : lines) {
                String low = line.toLowerCase();
                for (String key : KEYS) {
                    if (low.contains(key)) {
                        Log.i(TAG, "HIT " + f.getAbsolutePath() + "| " + trim(line));
                        hits++;
                        break;
                    }
                }
                if (hits >= 25) {
                    Log.i(TAG, "HIT ... truncated " + f.getAbsolutePath());
                    return;
                }
            }
            // binary blobs: pull printable runs too
            if (hits == 0 && looksBinary(b, n)) {
                for (String run : printableRuns(b, n)) {
                    Log.i(TAG, "BIN " + f.getName() + "| " + trim(run));
                }
            }
        } catch (Throwable t) {
            Log.i(TAG, "scan err " + f + ": " + t);
        } finally {
            if (in != null) {
                try {
                    in.close();
                } catch (Throwable ignored) {
                }
            }
        }
    }

    private static boolean looksBinary(byte[] b, int n) {
        for (int i = 0; i < n; i++) {
            if (b[i] == 0) {
                return true;
            }
        }
        return false;
    }

    private static java.util.List<String> printableRuns(byte[] b, int n) {
        java.util.List<String> out = new java.util.ArrayList<>();
        ByteArrayOutputStream cur = new ByteArrayOutputStream();
        for (int i = 0; i < n; i++) {
            int c = b[i] & 0xFF;
            if (c >= 32 && c < 127) {
                cur.write(c);
            } else {
                if (cur.size() >= 6) {
                    out.add(cur.toString());
                }
                cur.reset();
            }
        }
        if (cur.size() >= 6) {
            out.add(cur.toString());
        }
        return out;
    }

    private static String trim(String s) {
        String t = s.trim();
        return t.length() > 300 ? t.substring(0, 300) : t;
    }
}
