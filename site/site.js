// Marks the screen in view in the pinned run's index. Without script the index simply lists all five.
(() => {
  const links = [...document.querySelectorAll('.index a')];
  const shots = links.map((a) => document.querySelector(a.getAttribute('href')));
  if (!('IntersectionObserver' in window)) return;
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      const i = shots.indexOf(e.target);
      links.forEach((a, j) => (j === i ? a.setAttribute('aria-current', 'true') : a.removeAttribute('aria-current')));
    });
  }, { rootMargin: '-40% 0px -45% 0px' });
  shots.forEach((s) => s && io.observe(s));
})();
