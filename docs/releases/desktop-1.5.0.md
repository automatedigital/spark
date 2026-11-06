# Spark Desktop 1.5.0

Source base: main44be6d133494f7268eea6a7804bfd6d87395508b, including all25 feature heads via integrationPR239 and CI repair238. Desktop version manifests bumped together to1.5.0; verified production web bundle regenerated and committed at this release gate.

Validation: Node22.22.1; frontend production build/budget passes; frozen resource audit285 files/124 assets/zero problems; frozen backend startup passes. Backend inside Spark.app served UI/config schema/bundled skills and reports1.5.0/macos under isolated SPARK_HOME. Version/resource helper tests3 passed. Final app Developer ID deep/strict signature verification passes. No native GUI interaction or Windows package acceptance is claimed.

Build produced the signed49MiB DMG under src/spark_cli/web/src-tauri/target/release/bundle/dmg/Spark.dmg. Apple notarization initially failed because configured Keychain profile spark-notary was missing. Publication is blocked until notarization succeeds; do not call this artifact notarized or release it ad-hoc. Binary assets are not committed.
