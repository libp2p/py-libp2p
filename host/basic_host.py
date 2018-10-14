from host_interface import Host 

# Upon host creation, host takes in options, 
# including the list of addresses on which to listen.
# Host then parses these options and delegates to its Network instance, 
# telling it to listen on the given listen addresses.

class BasicHost(Host):
	pass