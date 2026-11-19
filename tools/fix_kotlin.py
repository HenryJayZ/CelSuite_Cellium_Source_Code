import re
from pathlib import Path

ROOT = Path("/home/henry/Documents/Projects/Python/Cellium/Android/cellium-app/app/src/main/java/HenryJayZ/CelSuite/Cellium")

def fix_file(p):
    if not p.exists(): return
    text = p.read_text(encoding="utf-8", errors="replace")
    orig = text
    
    # 1. Aggressive Un-minifier
    keywords = ['val', 'var', 'fun', 'if', 'for', 'while', 'return', 'import', 'class', 'override', 
                'private', 'public', 'internal', 'protected', 'when', 'try', 'catch', 'finally', 'throw',
                'LinearLayout', 'GlassMorph', 'SoundFX', 'CardView', 'ScrollView', 'TextView', 'Button',
                'EditText', 'ImageView', 'RecyclerView', 'FrameLayout', 'RelativeLayout', 'ConstraintLayout',
                'addView', 'removeView', 'setPadding', 'setOnClickListener', 'setText', 'setTextColor',
                'apply', 'let', 'run', 'also', 'with', 'lazy', 'dp', 'sp', 'updateQueueBar', 'refreshQueueBar']
    
    for kw in keywords:
        text = re.sub(rf'\}}([ \t]*)({kw})\b', r'}\n\1\2', text)
        text = re.sub(rf'\)({kw})\b', r')\n\1', text)
        text = re.sub(rf'"\)({kw})\b', r'")\n\1', text)
        
    # 2. Fix Anonymous Functions (handles modifiers like private/override/suspend)
    text = re.sub(r'((?:private|public|internal|protected|override|suspend|\s)*fun\s+\w+\s*\([^)]*\))\s*=\s*\{', r'\1 {', text)
    
    # 3. Fix Conflicting ViewGroup imports (strip all, add one at top)
    text = re.sub(r'import android\.view\.ViewGroup\n', '', text)
    if 'ViewGroup' in text and 'import android.view.ViewGroup' not in text:
        text = text.replace('import android.os.Bundle', 'import android.os.Bundle\nimport android.view.ViewGroup')
        
    # 4. Fix ShortArray -> ByteArray in UiIcons
    if p.name == "UiIcons.kt":
        text = text.replace('shortArrayOf(', 'byteArrayOf(')
        
    # 5. Fix cellium_prefs in MainActivity
    if p.name == "MainActivity.kt":
        if 'val prefs = context.getSharedPreferences("cellium_prefs"' in text:
            text = text.replace('val prefs = context.getSharedPreferences("cellium_prefs"', 'val cellium_prefs = context.getSharedPreferences("cellium_prefs"')
            text = re.sub(r'(?<!\.)\bprefs\.', 'cellium_prefs.', text)
            
    # 6. Fix onInit stub
    if "TextToSpeech.OnInitListener" in text and "override fun onInit" not in text:
        text = text.rsplit('}', 1)[0] + '\n    override fun onInit(status: Int) { /* Wave-10 stub */ }\n}'
        
    # 7. Balance braces
    open_b = text.count('{')
    close_b = text.count('}')
    if open_b > close_b:
        text += '\n}\n' * (open_b - close_b)
        
    if text != orig:
        p.write_text(text, encoding="utf-8")
        print(f"🔧 Fixed {p.name}")

for f in ["ui/MainActivity.kt", "ui/AvatarCanvas.kt", "data/KeyStore.kt", "ui/LiveCallActivity.kt", "ui/UiIcons.kt"]:
    fix_file(ROOT / f)
