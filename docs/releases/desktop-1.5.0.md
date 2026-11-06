# Spark Desktop 1.5.0

Source base: main44be6d133494f7268eea6a7804bfd6d87395508b, including all25 feature heads via integrationPR239 and CI repair238. Desktop version manifests bumped together to1.5.0; verified production web bundle regenerated and committed at this release gate.

Validation: Node22.22.1; frontend production build/budget passes; frozen resource audit285 files/124 assets/zero problems; frozen backend startup passes. Backend inside Spark.app served UI/config schema/bundled skills and reports1.5.0/macos under isolated SPARK_HOME. Version/resource helper tests3 passed. Final app Developer ID deep/strict signature verification passes. No native GUI interaction or Windows package acceptance is claimed.

Build produced the signed49MiB DMG under src/spark_cli/web/src-tauri/target/release/bundle/dmg/Spark.dmg. Apple notarization initially reported the profile missing while the interactive Mac session was locked. Vox release documentation records this Keychain-access failure mode. The unchanged spark-notary profile authenticated once accessible; no credentials were replaced. Apple accepted submission c8b98617-2df1-486c-9223-5d5c68f937c5; the ticket is stapled and validated. Gatekeeper accepts both DMG and the app mounted from it as Notarized Developer ID. Mounted app version1.5.0 verified; all139 packaged frontend files match the committed bundle. Binary assets are not committed.

Final DMG SHA-256: `11f22b6f3fa81f3f64704378ce046dc6328cd541cdab10ca19e9c816e903b441`.

Release: https://github.com/automatedigital/spark/releases/tag/desktop-v1.5.0
