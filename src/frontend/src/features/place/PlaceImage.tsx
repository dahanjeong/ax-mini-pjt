import { useState } from "react";
import defaultImage from "./assets/place-default.webp";
import type { PlaceImageProps } from "./types/index.ts";
import "./styles/PlaceImage.css";

// Representative photo in a fixed frame (the photo's own size never moves the card layout).
// No photo, or one that fails to load -> the bundled default illustration.
export function PlaceImage({ image, name }: PlaceImageProps) {
  const [failed, setFailed] = useState<string | null>(null);
  const photo = image && image !== failed ? image : null;

  return (
    <figure className="place-image">
      <img
        src={photo ?? defaultImage}
        alt={photo ? `${name} 사진` : ""}
        width={960}
        height={768}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setFailed(image)}
      />
      {photo && <figcaption className="place-image-credit">사진: 한국관광공사</figcaption>}
    </figure>
  );
}
