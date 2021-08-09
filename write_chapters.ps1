if ( $(Test-Path $args[0]) -and $(Test-Path $args[1]) ) {
	$vid = Get-Item $args[0]
	$chapters = Get-Item $args[1]
	$newvid = "$($vid.directoryname)\$($vid.basename).chaptered.mkv"

	# merge chapters
	Invoke-Expression "& 'C:\Program Files\MKVToolNix\mkvmerge.exe' --chapters '$chapters' -o '$newvid' '$($vid.fullname)'"

	$videometa = $(Get-Item -Stream video_metadata -Path "$($vid.fullname)" -ErrorAction SilentlyContinue)
	if ( $videometa.Stream -eq 'video_metadata' ) {
		Set-Content -Path "$newvid" -Stream video_metadata -Value $(Get-Content -Raw -Stream video_metadata -Path "$($vid.fullname)")
	}

	#Remove-Item "$($vid.fullname)"
	#Rename-Item -Path "$($vid.directoryname)\$($vid.basename).chaptered.mkv" -NewName "$($vid.basename).mkv"
}
