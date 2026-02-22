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
        <div className="relative w-full max-w-xs">
            <Carousel>
                <CarouselContent>
                    <CarouselItem className="p-4">
                        <div className="flex aspect-square items-center justify-center">
                            <img src = "../../cover1.jpg" />
                        </div>
                    </CarouselItem>
                    <CarouselItem className="p-4">
                        <div className="flex aspect-square items-center justify-center">
                            <img src = "../../cover2.jpg" />
                        </div>
                    </CarouselItem>
                </CarouselContent>
                <CarouselNavigation alwaysShow />
                <CarouselIndicator/>
            </Carousel>
        </div>
    );
};

