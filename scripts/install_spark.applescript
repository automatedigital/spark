-- Install Spark.app — one-click installer shipped on the Spark DMG.
-- Copies Spark.app to /Applications, clears download quarantine, and launches.
on run
	set installerPosix to POSIX path of (path to me as text)
	if installerPosix ends with "/" then
		set installerPosix to text 1 thru -2 of installerPosix
	end if
	set dmgRoot to do shell script "dirname " & quoted form of installerPosix
	set srcApp to dmgRoot & "/Spark.app"
	set destApp to "/Applications/Spark.app"

	try
		do shell script "test -d " & quoted form of srcApp
	on error
		display alert "Spark.app not found" message "Could not find Spark.app next to this installer on the disk image." as critical
		return
	end try

	try
		do shell script "xattr -cr " & quoted form of srcApp & " && rm -rf " & quoted form of destApp & " && ditto " & quoted form of srcApp & " " & quoted form of destApp & " && xattr -cr " & quoted form of destApp
	on error errMsg number errNum
		display alert "Install failed" message errMsg as critical
		return
	end try

	do shell script "open " & quoted form of destApp
end run
