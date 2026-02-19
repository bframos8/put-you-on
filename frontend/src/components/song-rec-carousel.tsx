"use client;"
import { 
    Carousel, 
    CarouselContent,
    CarouselNavigation,
    CarouselIndicator,
    CarouselItem
 } from "@/components/ui/carousel";

export function SongRecCarousel(){
    return (
        <Carousel
            className = "max-w-90">
            <img src = "../../cover1.jpg" />
            <img src = "../../cover2.jpg" />
        </Carousel>
    );
};

