#!/usr/bin/env ruby

require "tempfile"

path, name, dhcp_end = ARGV
abort "usage: configure-lima-network.rb PATH NAME DHCP_END" unless dhcp_end

content = File.read(path)
header = /^  #{Regexp.escape(name)}:\n/
match = content.match(header)
abort "network #{name.inspect} not found in #{path}" unless match

block_start = match.begin(0)
body_start = match.end(0)
next_header = content.match(/^  [A-Za-z0-9_.-]+:\n/, body_start)
block_end = next_header ? next_header.begin(0) : content.length
block = content[block_start...block_end]

if block.match?(/^    dhcpEnd:/)
  block = block.sub(/^    dhcpEnd:.*$/, "    dhcpEnd: #{dhcp_end}")
else
  insertion = block.match(/^    gateway:.*$/)
  abort "network #{name.inspect} has no gateway" unless insertion
  block = block.sub(
    /^    gateway:.*$/,
    "#{insertion[0]}\n    dhcpEnd: #{dhcp_end}"
  )
end

updated = content[0...block_start] + block + content[block_end..]
Tempfile.create(["networks", ".yaml"], File.dirname(path)) do |temporary|
  temporary.write(updated)
  temporary.flush
  temporary.fsync
  File.chmod(File.stat(path).mode & 0o777, temporary.path)
  File.rename(temporary.path, path)
end
