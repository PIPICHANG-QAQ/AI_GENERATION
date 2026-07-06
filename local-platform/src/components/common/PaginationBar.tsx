import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationEllipsis,
} from "@/components/ui/pagination";

function getPageList(current: number, count: number): (number | "ellipsis")[] {
  if (count <= 7) return Array.from({ length: count }, (_, i) => i + 1);
  const pages: (number | "ellipsis")[] = [1];
  const start = Math.max(2, current - 1);
  const end = Math.min(count - 1, current + 1);
  if (start > 2) pages.push("ellipsis");
  for (let i = start; i <= end; i++) pages.push(i);
  if (end < count - 1) pages.push("ellipsis");
  pages.push(count);
  return pages;
}

export function PaginationBar({
  page,
  pageSize,
  total,
  onPageChange,
  className,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  className?: string;
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  if (pageCount <= 1) return null;

  const list = getPageList(page, pageCount);
  const go = (p: number) => {
    if (p >= 1 && p <= pageCount && p !== page) onPageChange(p);
  };

  return (
    <Pagination className={className}>
      <PaginationContent>
        <PaginationItem>
          <PaginationLink
            href="#"
            size="default"
            aria-label="上一页"
            className={cn("gap-1 pl-2.5", page <= 1 && "pointer-events-none opacity-50")}
            onClick={(e) => {
              e.preventDefault();
              go(page - 1);
            }}
          >
            <ChevronLeft className="h-4 w-4" />
            <span>上一页</span>
          </PaginationLink>
        </PaginationItem>

        {list.map((p, i) => (
          <PaginationItem key={`${p}-${i}`}>
            {p === "ellipsis" ? (
              <PaginationEllipsis />
            ) : (
              <PaginationLink
                href="#"
                isActive={p === page}
                onClick={(e) => {
                  e.preventDefault();
                  go(p);
                }}
              >
                {p}
              </PaginationLink>
            )}
          </PaginationItem>
        ))}

        <PaginationItem>
          <PaginationLink
            href="#"
            size="default"
            aria-label="下一页"
            className={cn("gap-1 pr-2.5", page >= pageCount && "pointer-events-none opacity-50")}
            onClick={(e) => {
              e.preventDefault();
              go(page + 1);
            }}
          >
            <span>下一页</span>
            <ChevronRight className="h-4 w-4" />
          </PaginationLink>
        </PaginationItem>
      </PaginationContent>
    </Pagination>
  );
}
