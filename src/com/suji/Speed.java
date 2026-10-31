package com.suji;

import android.content.Context;
import android.util.Log;

/**
 * Playback speed controller, headless.
 *
 * The patched player reads {@link #CURRENT} whenever it builds a PlaySpeed. Speed is
 * changed from the LAN page served by {@link Web}; nothing is drawn on the TV and no
 * remote key is intercepted.
 */
public final class Speed {
    private static final String TAG = "SUJIDBG";

    private static final float[] STEPS = {1.0f, 1.25f, 1.5f, 1.75f, 2.0f};
    private static int index = 0;                       // default 1.0x (stock)
    public static volatile float CURRENT = 1.0f;

    /** Set from JPlayer2.Play so a speed change can be pushed into the live player. */
    public static volatile Object player;

    private Speed() {}

    private static Context appCtx;

    /** Called from MainActivity.onCreate; starts the LAN control page and restores speed. */
    public static void attach(Context ctx) {
        try {
            appCtx = ctx.getApplicationContext();
            CURRENT = appCtx.getSharedPreferences("suji_speed", Context.MODE_PRIVATE)
                    .getFloat("speed", 1.0f);
            index = nearestIndex(CURRENT);
            Log.i(TAG, "SPEED restored: " + CURRENT);
        } catch (Throwable t) {
            Log.i(TAG, "SPEED restore failed: " + t);
        }
        try {
            Web.start();
        } catch (Throwable t) {
            Log.i(TAG, "SPEED attach failed: " + t);
        }
    }

    private static int nearestIndex(float speed) {
        int best = 0;
        for (int i = 0; i < STEPS.length; i++) {
            if (Math.abs(STEPS[i] - speed) < Math.abs(STEPS[best] - speed)) {
                best = i;
            }
        }
        return best;
    }

    /** Called from JPlayer2.Pause-on-resume paths to keep the live player reference. */
    public static void setPlayer(Object p) {
        player = p;
    }

    /** Set speed from the LAN page. Any value in 1.0..2.0 is accepted. */
    public static void setFromOutside(float speed) {
        float value = Math.max(1.0f, Math.min(2.0f, speed));
        int bestIndex = 0;
        for (int i = 0; i < STEPS.length; i++) {
            if (Math.abs(STEPS[i] - value) < Math.abs(STEPS[bestIndex] - value)) {
                bestIndex = i;
            }
        }
        if (value == CURRENT) {
            apply();
            return;
        }
        index = bestIndex;
        CURRENT = value;
        Log.i(TAG, "SPEED set from web: " + CURRENT);
        try {
            if (appCtx != null) {
                appCtx.getSharedPreferences("suji_speed", Context.MODE_PRIVATE)
                        .edit().putFloat("speed", CURRENT).apply();
            }
        } catch (Throwable t) {
            Log.i(TAG, "SPEED persist failed: " + t);
        }
        apply();
    }

    /** Reflectively call JPlayer2.Play(float) so the running pipeline picks up the change. */
    private static void apply() {
        Object p = player;
        if (p == null) {
            return;
        }
        try {
            p.getClass().getMethod("Play", float.class).invoke(p, CURRENT);
            Log.i(TAG, "SPEED applied to live player: " + CURRENT);
        } catch (Throwable t) {
            Log.i(TAG, "SPEED apply failed: " + t);
        }
    }
}
