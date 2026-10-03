package com.mrfounders.kisanmitra;

import android.os.Bundle;
import androidx.activity.EdgeToEdge;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Draw behind the status and navigation bars (required look on Android 15+).
        // Capacitor passes the bar sizes to the page as --safe-area-inset-* CSS variables.
        // Must run after super.onCreate(): before it, the window would be built with the
        // launch (splash) theme and get an action bar.
        EdgeToEdge.enable(this);
    }
}
