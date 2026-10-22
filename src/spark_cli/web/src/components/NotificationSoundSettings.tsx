import { useState } from "react";
import { getNotificationPreferences, saveNotificationPreferences, type NotificationPreferences } from "@/lib/notificationPolicy";
import { notificationSound, type SoundClass } from "@/lib/notificationSound";

export function NotificationSoundSettings() {
  const [prefs, setPrefs] = useState(getNotificationPreferences);
  const [message, setMessage] = useState("");
  const update = (changes: Partial<NotificationPreferences>) => {
    const next = { ...getNotificationPreferences(), ...changes };
    try { saveNotificationPreferences(next); setPrefs(next); setMessage(""); }
    catch { setMessage("Could not save sound preferences."); }
  };
  const preview = async (sound: SoundClass) => {
    const result = await notificationSound.preview(sound);
    setMessage(result === "played" ? "Preview played." : result === "suppressed" ? "Wait a few seconds before another preview." : "Sound unavailable. Allow audio in this browser or desktop window, then try Preview again.");
  };
  return <fieldset className="border-b border-border px-4 py-3 text-xs space-y-2">
    <legend className="sr-only">Notification sounds</legend>
    <p className="font-medium">Notification sounds</p>
    <p className="text-muted-foreground">Off by default. Quiet hours and project mutes apply. Preview enables audio for this window and ignores quiet hours.</p>
    <label className="flex items-center gap-2"><input type="checkbox" checked={prefs.completions} onChange={e => update({ completions: e.target.checked })} />Completion alerts</label>
    <p className="text-muted-foreground">Completion sounds require completion alerts. Input sounds follow approval and question alert preferences.</p>
    {([[ 'completion', 'Completion sounds', 'completionSound'], ['input', 'Input request sounds', 'inputSound']] as const).map(([sound, label, key]) => <div key={sound} className="flex items-center justify-between gap-2">
      <label className="flex items-center gap-2"><input type="checkbox" checked={prefs[key]} onChange={e => update({ [key]: e.target.checked })} />{label}</label>
      <button type="button" className="underline" aria-label={`Preview ${sound} sound`} onClick={() => void preview(sound)}>Preview</button>
    </div>)}
    <p role="status" className="text-muted-foreground">{message}</p>
  </fieldset>;
}
