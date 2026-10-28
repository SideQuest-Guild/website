// Charter pages: the contents rail marks the article being read. Without JS the rail is plain anchor links.
const links = new Map(
  Array.from(document.querySelectorAll<HTMLAnchorElement>("[data-toc]"), (link) => [link.dataset.toc ?? "", link]),
);
const sections = Array.from(links.keys(), (id) => document.getElementById(id)).filter(
  (section): section is HTMLElement => section !== null,
);

/** The article being read: the last one whose heading has reached the top of the screen, or the last at the page end. */
function currentId(): string | undefined {
  const atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
  if (atEnd) {
    return sections.at(-1)?.id;
  }
  // Low enough that a two-line article doesn't hand over to the next one while its own heading is still in view.
  const line = window.innerHeight * 0.15;
  let current = sections[0]?.id;
  for (const section of sections) {
    if (section.getBoundingClientRect().top > line) {
      break;
    }
    current = section.id;
  }
  return current;
}

let marked: string | undefined;
let queued = false;

function update(): void {
  queued = false;
  const id = currentId();
  if (id === marked) {
    return;
  }
  marked = id;
  for (const [key, link] of links) {
    if (key === id) {
      link.setAttribute("aria-current", "true");
    } else {
      link.removeAttribute("aria-current");
    }
  }
}

if (sections.length > 0) {
  const schedule = (): void => {
    if (!queued) {
      queued = true;
      requestAnimationFrame(update);
    }
  };
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  update();
}
