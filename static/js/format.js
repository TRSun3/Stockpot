// How freshness and dates read on the page.

const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

export function freshnessLabel(item) {
  const days = item.days_left;
  switch (item.status) {
    case "expired":
      return `Expired ${plural(-days, "day")} ago`;
    case "today":
      return "Expires today";
    case "soon":
      return days === 1 ? "Expires tomorrow" : `Expires in ${plural(days, "day")}`;
    case "fresh":
      return `Fresh · ${plural(days, "day")} left`;
    default:
      return "No expiry";
  }
}

export function minutes(count) {
  if (count < 60) return `${count} min`;
  const hours = Math.floor(count / 60);
  const rest = count % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}
