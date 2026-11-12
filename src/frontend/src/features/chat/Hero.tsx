import "../../components/ui/styles/commonStyle.css";
import "./styles/Hero.css";

// Welcome panel over a torn hill strip, shown before the first question.
export function Hero() {
  return (
    <section className="surface-paper hero" aria-label="소개">
      <h2>아기와 함께라면 어디든 소풍이에요</h2>
      <p>수유실·유모차 대여·주차부터 날씨와 미세먼지까지 한 번에 확인해 드릴게요.</p>
    </section>
  );
}
