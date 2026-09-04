import { useEffect, useState } from "react";

/**
 * Tracks which anchored section is currently in view (scroll-spy).
 *
 * `observeKey` should change whenever lazily-loaded sections mount, so the
 * observer attaches to elements that did not exist on first render.
 */
export function useActiveSection(ids: readonly string[], observeKey: unknown = null) {
  const [active, setActive] = useState(ids[0]);
  const key = ids.join(",");

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActive(entry.target.id);
          }
        }
      },
      { rootMargin: "-20% 0px -60% 0px" },
    );

    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }

    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, observeKey]);

  return active;
}
