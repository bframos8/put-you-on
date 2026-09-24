# The only variable in this config, and deliberately the only one: there is exactly one
# environment (6.5), so everything else is pinned directly in the resource files where you
# can read it without chasing an indirection.
#
# The instance class is the exception because 10.2 needs a *temporary* scale-up. Building
# the HNSW index on `songs` needs the whole graph to fit in maintenance_work_mem — roughly
# 650 MiB for 110,861 vectors at 1280 dims (the per-row cost is the vector itself plus
# ~674 bytes of element and neighbour-list overhead; ef_construction does not enter it).
# db.t4g.micro reports ~756 MB of usable memory, so after shared_buffers there is nowhere
# near enough and the build spills to disk, which is what killed the earlier attempt.
# *Serving* the index needs no such headroom. Only the build does, so the larger class is
# rented for an hour rather than kept.
#
#   terraform apply -var 'db_instance_class=db.t4g.medium'   # scale up for the build
#   terraform apply                                          # back to the default
#
# Doing it this way rather than editing rds.tf means the scaled-up value is never
# committed, so any later plain apply pulls the instance back down on its own. There is no
# way to forget and leave it running large and billing for it.
variable "db_instance_class" {
  description = "RDS instance class. Raise temporarily for an index build (gameplan 10.2), then let the default restore it."
  type        = string
  default     = "db.t4g.micro"
}
