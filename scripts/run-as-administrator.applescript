on run argv
	if (count of argv) is not 1 then
		error "Expected one shell command argument"
	end if
	do shell script (item 1 of argv) with administrator privileges
end run
