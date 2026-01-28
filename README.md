```mermaid graph TD
    subgraph Internet
        CF[Cloudflare: The Mist]
    end

    subgraph Pi4_Edge [The Crow's Nest: Raspberry Pi 4]
        Nginx[Nginx: Harbor Master]
        Web[Powderchest Dashboard]
    end

    subgraph Pi5_Compute [The Galleon: Raspberry Pi 5]
        Docker[Docker Engine]
        subgraph Containers [The Crew]
            MC[Minecraft Servers]
            PH[Pi-Hole / Unbound]
            WG[WireGuard]
            OL[Ollama AI]
        end
        BM[BlueMap Renderer]
    end

    subgraph Storage [The Treasure Chest]
        SSD[(Samba SSD)]
    end

    %% Connections
    CF <--> Nginx
    Nginx <--> Web
    Web <--> BM
    Docker --- Containers
    Containers --- SSD
    BM --- SSD
    MC --- BM```