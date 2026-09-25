# The only variable in this config, and deliberately the only one: there is exactly one
# environment (6.5), so everything else is pinned directly in the resource files where you
# can read it without chasing an indirection.
#
# The instance class is the exception because 10.2 needed a *temporary* scale-up to build
# the HNSW index: the graph must fit in maintenance_work_mem — roughly 650 MiB for 110,861
# vectors at 1280 dims (the per-row cost is the vector itself plus ~674 bytes of element
# and neighbour-list overhead; ef_construction does not enter it). Keeping the size in a
# variable means a raised value is never committed, so a later plain apply always pulls
# the instance back to the default:
#
#   terraform apply -var 'db_instance_class=db.t4g.large'   # rent headroom for a build
#   terraform apply                                         # back to the default
#
# The default is **small, not micro**, for two reasons found on 2026-09-25:
#
#   1. It suits the workload. Serving an 858 MB index over a 674 MB table, small's
#      ~413 MB of shared_buffers keeps warm vector queries at 6-10 ms touching ~1,300-3,600
#      buffers. Micro's ~180 MB cannot hold that working set, and micro failing to cache
#      it is exactly what produced the 8.08 s pre-index baseline. Micro is *viable* now
#      that the index exists; small is better suited, for about $12/mo.
#   2. AWS had no db.t4g.micro capacity in us-east-1a for over two hours of retries
#      (nor medium, which is why the index was built on small). Leaving the default at a
#      class that cannot be obtained means every future apply — including one run for an
#      unrelated reason — tries to scale down and either errors or reboots the database at
#      a moment nobody chose.
variable "db_instance_class" {
  description = "RDS instance class. Raise temporarily for an index build (gameplan 10.2), then let the default restore it."
  type        = string
  default     = "db.t4g.small"
}
