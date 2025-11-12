"use client"

import { useState, useMemo } from "react"
import { type Film, type Image as ImageType, type Filmstock, getImageUrl } from "@/lib/api"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import Link from "next/link"
import Image from "next/image"
import { Search } from "lucide-react"

interface SearchInterfaceProps {
  films: Film[]
  images: ImageType[]
  filmstocks: Filmstock[]
}

export function SearchInterface({ films, images, filmstocks }: SearchInterfaceProps) {
  const [searchQuery, setSearchQuery] = useState("")
  const [filmstockFilter, setFilmstockFilter] = useState("all")
  const [dateRangeStart, setDateRangeStart] = useState("")
  const [dateRangeEnd, setDateRangeEnd] = useState("")

  const filteredFilms = useMemo(() => {
    return films.filter((film) => {
      const matchesQuery =
        !searchQuery ||
        film.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        film.notes?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        film.camera?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        film.lens?.toLowerCase().includes(searchQuery.toLowerCase())

      const matchesFilmstock =
        filmstockFilter === "all" ||
        film.film_type === filmstocks.find((f) => f.id.toString() === filmstockFilter)?.name

      const matchesDateRange =
        (!dateRangeStart || !film.start_date || film.start_date >= dateRangeStart) &&
        (!dateRangeEnd || !film.end_date || film.end_date <= dateRangeEnd)

      return matchesQuery && matchesFilmstock && matchesDateRange
    })
  }, [films, searchQuery, filmstockFilter, dateRangeStart, dateRangeEnd, filmstocks])

  const filteredImages = useMemo(() => {
    return images.filter((image) => {
      const film = films.find((f) => f.id === image.film_roll_id)

      const matchesQuery =
        !searchQuery ||
        image.notes?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        film?.title.toLowerCase().includes(searchQuery.toLowerCase())

      const matchesFilmstock =
        filmstockFilter === "all" ||
        film?.film_type === filmstocks.find((f) => f.id.toString() === filmstockFilter)?.name

      const matchesDateRange =
        (!dateRangeStart || !image.capture_date || image.capture_date >= dateRangeStart) &&
        (!dateRangeEnd || !image.capture_date || image.capture_date <= dateRangeEnd)

      return matchesQuery && matchesFilmstock && matchesDateRange
    })
  }, [images, films, searchQuery, filmstockFilter, dateRangeStart, dateRangeEnd, filmstocks])

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="pt-6">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-2 lg:col-span-2">
              <Label htmlFor="search">Search</Label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="search"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search by title, notes, equipment..."
                  className="pl-9"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="filmstock">Filmstock</Label>
              <Select value={filmstockFilter} onValueChange={setFilmstockFilter}>
                <SelectTrigger id="filmstock">
                  <SelectValue placeholder="All filmstocks" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All filmstocks</SelectItem>
                  {filmstocks.map((filmstock) => (
                    <SelectItem key={filmstock.id} value={filmstock.id.toString()}>
                      {filmstock.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Date Range</Label>
              <div className="flex gap-2">
                <Input
                  type="date"
                  value={dateRangeStart}
                  onChange={(e) => setDateRangeStart(e.target.value)}
                  placeholder="Start"
                />
                <Input
                  type="date"
                  value={dateRangeEnd}
                  onChange={(e) => setDateRangeEnd(e.target.value)}
                  placeholder="End"
                />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="films" className="w-full">
        <TabsList className="grid w-full max-w-md grid-cols-2">
          <TabsTrigger value="films">Films ({filteredFilms.length})</TabsTrigger>
          <TabsTrigger value="images">Images ({filteredImages.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="films" className="mt-6">
          {filteredFilms.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-center">
              <p className="text-lg font-medium text-muted-foreground">No films found</p>
              <p className="mt-1 text-sm text-muted-foreground">Try adjusting your search filters</p>
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {filteredFilms.map((film) => (
                <Link key={film.id} href={`/films/${film.id}`}>
                  <Card className="transition-shadow hover:shadow-lg">
                    <CardContent className="p-4">
                      <h3 className="font-semibold">{film.title}</h3>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {film.camera && (
                          <Badge variant="secondary" className="text-xs">
                            {film.camera}
                          </Badge>
                        )}
                        {film.lens && (
                          <Badge variant="outline" className="text-xs">
                            {film.lens}
                          </Badge>
                        )}
                        {film.film_type && (
                          <Badge variant="outline" className="text-xs">
                            {film.film_type}
                          </Badge>
                        )}
                      </div>
                      {(film.start_date || film.end_date) && (
                        <p className="mt-2 text-xs text-muted-foreground">
                          {film.start_date && new Date(film.start_date).toLocaleDateString()}
                          {film.start_date && film.end_date && " – "}
                          {film.end_date && new Date(film.end_date).toLocaleDateString()}
                        </p>
                      )}
                      {film.notes && <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{film.notes}</p>}
                    </CardContent>
                  </Card>
                </Link>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="images" className="mt-6">
          {filteredImages.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-center">
              <p className="text-lg font-medium text-muted-foreground">No images found</p>
              <p className="mt-1 text-sm text-muted-foreground">Try adjusting your search filters</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
              {filteredImages.map((image) => {
                const film = films.find((f) => f.id === image.film_roll_id)
                return (
                  <Link key={image.id} href={`/images/${image.id}`}>
                    <Card className="group overflow-hidden transition-shadow hover:shadow-lg">
                      <div className="relative aspect-square overflow-hidden bg-muted">
                        <Image
                          src={getImageUrl(image) || "/placeholder.svg"}
                          alt={`Frame ${image.frame_number || "unknown"}`}
                          fill
                          className="object-cover transition-transform group-hover:scale-105"
                          sizes="(max-width: 768px) 50vw, (max-width: 1024px) 33vw, (max-width: 1280px) 25vw, 20vw"
                        />
                      </div>
                      <CardContent className="p-3">
                        <div className="flex items-center justify-between">
                          <span className="truncate text-xs font-medium">
                            {image.type === "scan" ? "Scan" : "Contact"}
                          </span>
                          {image.frame_number && (
                            <Badge variant="secondary" className="text-xs">
                              #{image.frame_number}
                            </Badge>
                          )}
                        </div>
                        {film && <p className="mt-1 truncate text-xs text-muted-foreground">{film.title}</p>}
                      </CardContent>
                    </Card>
                  </Link>
                )
              })}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
