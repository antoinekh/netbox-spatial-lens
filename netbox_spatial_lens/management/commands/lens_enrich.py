"""
Fill in what the demo data leaves blank.

netbox-demo-data is rich in racks, devices and cables but empty in exactly the fields this
plugin draws with: no rack has outer dimensions, none has a cooling capability, no site is
geocoded, and the large racks hold nothing at all. A view that reads those fields therefore
renders a room of grey boxes, which proves nothing either way.

This fills them, on demo data only. It touches nothing that already has a value, so running it
against a real inventory cannot overwrite a measurement somebody took.

Every part is separately selectable, because "enrich my database" is not something to hand a
command without saying what it will do.
"""

import random

from dcim.models import (
    Cable,
    Device,
    DeviceRole,
    DeviceType,
    Interface,
    PowerOutlet,
    PowerPort,
    Rack,
    Site,
)
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Q

# Rack cabinets in the wild are 600 or 800 mm wide and 1000 to 1200 mm deep.
CABINET_SIZES = ((600, 1070), (600, 1200), (800, 1070), (800, 1200))

# Cooling, weighted so most of a room is air and liquid is the exception, which is what makes
# the colouring worth looking at: a uniform room says nothing.
COOLING = (
    ('air-only', 8, (3, 8)),
    ('hybrid', 3, (10, 20)),
    ('liquid-only', 1, (30, 60)),
)

# Roughly the sites in the demo data, which are US north-east. Enough to put pins on a map in
# the right places; not a substitute for real coordinates.
GEO_BOX = ((40.6, -75.5), (43.2, -71.0))


class Command(BaseCommand):
    help = 'Fill in the demo-data fields this plugin draws with. Never overwrites an existing value.'

    def add_arguments(self, parser):
        parser.add_argument('--racks', action='store_true', help='Rack footprints, cooling and airflow.')
        parser.add_argument('--geo', action='store_true', help='Site latitude and longitude.')
        parser.add_argument('--fill', action='store_true', help='Mount devices in racks that stand empty.')
        parser.add_argument('--cable', action='store_true', help='Cable and power the devices --fill mounted.')
        parser.add_argument(
            '--circuits',
            action='store_true',
            help='Direct site-to-site circuits, so the map shows DC-to-DC links.',
        )
        parser.add_argument(
            '--europe',
            action='store_true',
            help='Add European sites and transatlantic circuits, for a worldwide map.',
        )
        parser.add_argument(
            '--uplinks',
            action='store_true',
            help='Cable each rack top-of-rack switch to a pair of spines in other racks.',
        )
        parser.add_argument(
            '--plans',
            action='store_true',
            help='A schematic architect drawing under each floor, so the background layer has something to show.',
        )
        parser.add_argument('--all', action='store_true', help='Everything above.')
        parser.add_argument('--seed', type=int, default=1, help='Random seed, so a run repeats (default: 1).')

    def handle(self, *args, **options):
        random.seed(options['seed'])
        steps = ('racks', 'geo', 'fill', 'cable', 'circuits', 'europe', 'uplinks', 'plans')
        run_all = options['all'] or not any(options[k] for k in steps)

        # Europe first, because it creates sites and racks that every step below then treats
        # like any other: measured, filled, cabled. Running it last left four European rooms
        # standing empty, which is exactly the "no data" the rest of this command exists to
        # remove.
        if run_all or options['europe']:
            self.add_europe()
        if run_all or options['racks']:
            self.enrich_racks()
        if run_all or options['geo']:
            self.enrich_sites()
        if run_all or options['fill']:
            self.fill_racks()
        if run_all or options['cable']:
            self.cable_racks()
        if run_all or options['uplinks']:
            self.link_uplinks()
        if run_all or options['circuits']:
            self.link_sites()
        if run_all or options['plans']:
            self.add_plans()

    # ------------------------------------------------------------------ racks

    def enrich_racks(self):
        changed = 0
        for rack in Rack.objects.all():
            fields = []
            if rack.outer_width is None and rack.outer_depth is None:
                width, depth = random.choice(CABINET_SIZES)
                rack.outer_width, rack.outer_depth, rack.outer_unit = width, depth, 'mm'
                fields += ['outer_width', 'outer_depth', 'outer_unit']
            if not rack.cooling_capability:
                capability, _, (low, high) = random.choices(COOLING, weights=[w for _, w, _ in COOLING])[0]
                rack.cooling_capability = capability
                rack.cooling_capacity = round(random.uniform(low, high), 1)
                fields += ['cooling_capability', 'cooling_capacity']
            if not rack.airflow:
                rack.airflow = 'front-to-rear'
                fields.append('airflow')
            if fields:
                rack.save(update_fields=fields)
                changed += 1
        self.stdout.write(self.style.SUCCESS(f'racks:  enriched {changed}'))

    def enrich_sites(self):
        (lat_lo, lon_lo), (lat_hi, lon_hi) = GEO_BOX
        changed = 0
        for site in Site.objects.filter(latitude=None):
            site.latitude = round(random.uniform(lat_lo, lat_hi), 6)
            site.longitude = round(random.uniform(lon_lo, lon_hi), 6)
            site.save(update_fields=['latitude', 'longitude'])
            changed += 1
        self.stdout.write(self.style.SUCCESS(f'sites:  geocoded {changed}'))

    # ------------------------------------------------------------------ fill

    def _pick_types(self):
        """
        A switch type and some server types to fill racks with.

        Chosen from what the database already holds rather than created, so the enriched racks
        are made of the same equipment as the rest of the demo data.
        """
        # A device gets its ports from its type's templates, so a type with no interface
        # templates produces a device with nothing to cable. Picked by template count for
        # that reason, not by name.
        with_ports = DeviceType.objects.annotate(
            ifaces=Count('interfacetemplates', distinct=True),
            psus=Count('powerporttemplates', distinct=True),
        )
        switch = with_ports.filter(u_height=1, ifaces__gte=8).order_by('-ifaces').first()
        servers = list(
            with_ports.filter(u_height__in=(1, 2), ifaces__gte=1, psus__gte=1)
            .exclude(pk=switch.pk if switch else None)
            .order_by('-psus')[:4]
        )
        return switch, servers

    def fill_racks(self):
        switch_type, server_types = self._pick_types()
        if not switch_type or not server_types:
            self.stdout.write(
                self.style.WARNING(
                    'fill:   no device type carries both interface and power-port templates; nothing to mount'
                )
            )
            return
        role = DeviceRole.objects.filter(name__icontains='compute').first() or DeviceRole.objects.first()
        switch_role = DeviceRole.objects.filter(name__icontains='infra').first() or role

        # A PDU is a device type carrying power outlets. Picked the same way as the others,
        # by what it can do rather than by what it is called.
        pdu_type = (
            DeviceType.objects.annotate(outlets=Count('poweroutlettemplates'))
            .filter(outlets__gte=8, u_height__lte=2)
            .order_by('-outlets')
            .first()
        )
        pdu_role = DeviceRole.objects.filter(name__icontains='power').first() or switch_role

        filled = mounted = 0
        for rack in Rack.objects.annotate().all():
            if Device.objects.filter(rack=rack).exists():
                continue  # Never touch a rack that already holds something.
            site, location = rack.site, rack.location

            # A top-of-rack switch at the top unit, then servers filling upward from the
            # bottom, which is how a cabinet is actually built.
            top = rack.u_height
            created = []
            switch = Device.objects.create(
                name=f'{rack.name.lower()}-tor01',
                device_type=switch_type,
                role=switch_role,
                site=site,
                location=location,
                rack=rack,
                position=top,
                face='front',
                status='active',
            )
            created.append(switch)

            # A PDU at the bottom, so the rack has outlets and a power chain to trace. Without
            # one the servers' power ports have nothing to plug into and the chain is empty.
            if pdu_type:
                created.append(
                    Device.objects.create(
                        name=f'{rack.name.lower()}-pdu01',
                        device_type=pdu_type,
                        role=pdu_role,
                        site=site,
                        location=location,
                        rack=rack,
                        position=1,
                        face='front',
                        status='active',
                    )
                )

            position = 2 if pdu_type else 1
            while position + 2 <= top - 1 and len(created) < 12:
                device_type = random.choice(server_types)
                height = int(device_type.u_height)
                created.append(
                    Device.objects.create(
                        name=f'{rack.name.lower()}-srv{len(created):02}',
                        device_type=device_type,
                        role=role,
                        site=site,
                        location=location,
                        rack=rack,
                        position=position,
                        face='front',
                        status='active',
                    )
                )
                position += height + 1

            filled += 1
            mounted += len(created)
        self.stdout.write(self.style.SUCCESS(f'fill:   {mounted} device(s) into {filled} empty rack(s)'))

    # ----------------------------------------------------------------- cable

    def cable_racks(self):
        """
        Cable each server's first interface to its top-of-rack switch, and its power port to
        a rack outlet where one exists.

        Only devices this command created are touched. A demo cable somebody drew by hand, or
        a real one, is left exactly as it is.
        """
        made = 0
        for rack in Rack.objects.all():
            switch = Device.objects.filter(rack=rack, name__endswith='-tor01').first()
            if not switch:
                continue
            switch_ports = list(Interface.objects.filter(device=switch, cable=None).order_by('name'))
            outlets = list(PowerOutlet.objects.filter(device__rack=rack, cable=None).order_by('name'))

            servers = Device.objects.filter(rack=rack, name__contains='-srv').order_by('position')
            for server in servers:
                made += self._cable_data(server, switch_ports)
                made += self._cable_power(server, outlets)
            made += self._cable_pdu_to_feed(rack)
        self.stdout.write(self.style.SUCCESS(f'cable:  created {made} cable(s)'))

    def _cable(self, a, b):
        """
        One cable between two terminations.

        Built through `a_terminations` and `b_terminations`, which is what makes NetBox
        construct the `CablePath` behind the cable. Creating the termination rows directly
        leaves the link looking perfectly cabled while `trace()` returns nothing, so every
        path in the rack view came back empty.
        """
        with transaction.atomic():
            cable = Cable(status='connected', a_terminations=[a], b_terminations=[b])
            cable.save()
        return 1

    def _cable_data(self, server, switch_ports):
        # One uplink per server. Without this check a second run gives every server a second
        # cable, because its next free interface is always a different one.
        if Interface.objects.filter(device=server).exclude(cable=None).exists():
            return 0
        port = Interface.objects.filter(device=server, cable=None).order_by('name').first()
        if not port or not switch_ports:
            return 0
        return self._cable(port, switch_ports.pop(0))

    def _cable_power(self, server, outlets):
        if PowerPort.objects.filter(device=server).exclude(cable=None).exists():
            return 0
        power_port = PowerPort.objects.filter(device=server, cable=None).order_by('name').first()
        if not power_port or not outlets:
            return 0
        return self._cable(power_port, outlets.pop(0))

    # -------------------------------------------------------------- site links

    def link_sites(self):
        """
        Direct circuits between the largest sites.

        Every circuit in netbox-demo-data runs from a branch to a provider network, which is a
        real hub-and-spoke WAN but leaves no site-to-site link to draw. This adds a small ring
        between the biggest sites, which is what a core between data centres looks like.
        """
        from circuits.models import Circuit, CircuitTermination, CircuitType, Provider

        sites = list(Site.objects.annotate(n=Count('racks')).filter(n__gt=0).order_by('-n')[:5])
        if len(sites) < 2:
            self.stdout.write(self.style.WARNING('links:  fewer than two sites hold racks'))
            return

        provider = Provider.objects.first()
        if not provider:
            self.stdout.write(self.style.WARNING('links:  no provider to attach a circuit to'))
            return
        circuit_type, _ = CircuitType.objects.get_or_create(slug='dark-fibre', defaults={'name': 'Dark fibre'})

        made = 0
        # A ring, so every site has two paths out, which is the point of a core.
        for index, site in enumerate(sites):
            peer = sites[(index + 1) % len(sites)]
            cid = f'CORE-{site.slug[:8].upper()}-{peer.slug[:8].upper()}'
            if Circuit.objects.filter(cid=cid).exists():
                continue
            with transaction.atomic():
                circuit = Circuit.objects.create(
                    cid=cid,
                    provider=provider,
                    type=circuit_type,
                    status='active',
                    commit_rate=10_000_000,  # 10 Gbps, in kbps
                    description=f'Core link {site} to {peer}',
                )
                for side, end in (('A', site), ('Z', peer)):
                    CircuitTermination.objects.create(circuit=circuit, term_side=side, termination=end)
            made += 1
        self.stdout.write(self.style.SUCCESS(f'links:  created {made} site-to-site circuit(s)'))

    def _cable_pdu_to_feed(self, rack):
        """
        Cable each PDU's inlet to a power feed in its rack.

        Without this a power chain stops at the outlet: the demo data cables servers to PDUs
        but never cables a PDU to anything, so tracing a server's power reaches a socket and
        no further. Joining the two makes the chain the thing it is meant to be, from the
        device all the way back to the panel.
        """
        from dcim.models import PowerFeed

        feeds = list(PowerFeed.objects.filter(rack=rack, cable=None).order_by('name'))
        if not feeds:
            return 0

        made = 0
        pdus = Device.objects.filter(rack=rack).filter(
            Q(name__icontains='pdu') | Q(device_type__model__icontains='pdu')
        )
        for pdu in pdus:
            inlet = PowerPort.objects.filter(device=pdu, cable=None).order_by('name').first()
            if not inlet or not feeds:
                continue
            made += self._cable(inlet, feeds.pop(0))
        return made

    # ---------------------------------------------------------------- europe

    # Real coordinates, so the map reads as a world rather than as scattered dots. These are
    # the cities the European carrier interconnects actually sit in.
    EUROPEAN_SITES = (
        ('EU-Frankfurt', 50.110924, 8.682127),
        ('EU-Amsterdam', 52.370216, 4.895168),
        ('EU-London', 51.507351, -0.127758),
        ('EU-Paris', 48.856613, 2.352222),
    )

    def add_europe(self):
        """
        A second continent, and the circuits reaching it.

        The demo data is one American region, so a map of it says nothing about how the view
        behaves at world scale: every site sits within a few degrees of its neighbours. These
        four put real distance on the map, and the transatlantic circuit gives it the long
        arc that is the whole point of drawing links geographically.
        """
        from circuits.models import Circuit, CircuitTermination, CircuitType, Provider
        from dcim.models import Rack, RackRole, SiteGroup

        provider = Provider.objects.first()
        if not provider:
            self.stdout.write(self.style.WARNING('europe: no provider to attach a circuit to'))
            return
        circuit_type, _ = CircuitType.objects.get_or_create(slug='transatlantic', defaults={'name': 'Transatlantic'})
        group, _ = SiteGroup.objects.get_or_create(slug='europe', defaults={'name': 'Europe'})
        rack_role = RackRole.objects.first()

        anchor = Site.objects.annotate(n=Count('racks')).filter(n__gt=0).order_by('-n').first()
        created_sites, created_racks, sites = 0, 0, []
        for name, lat, lon in self.EUROPEAN_SITES:
            site, made = Site.objects.get_or_create(
                slug=name.lower(),
                defaults={
                    'name': name,
                    'status': 'active',
                    'group': group,
                    'latitude': lat,
                    'longitude': lon,
                },
            )
            sites.append(site)
            created_sites += int(made)
            if not made:
                continue
            # A site with no racks is a dot with no size, because the marker scales by rack
            # count, so an empty one would read as insignificant rather than as new.
            for index in range(1, 5):
                Rack.objects.create(
                    name=f'{name}-R{index:02}',
                    site=site,
                    role=rack_role,
                    status='active',
                    u_height=42,
                    width=19,
                )
                created_racks += 1

        made = 0
        if anchor:
            # A ring across Europe, then one transatlantic hop: local resilience plus a long
            # haul to the other region, which is how a real estate is built.
            pairs = [(sites[i], sites[(i + 1) % len(sites)]) for i in range(len(sites))]
            pairs.append((sites[0], anchor))
            for a, z in pairs:
                cid = f'CORE-{a.slug[:10].upper()}-{z.slug[:10].upper()}'
                if Circuit.objects.filter(cid=cid).exists():
                    continue
                with transaction.atomic():
                    circuit = Circuit.objects.create(
                        cid=cid,
                        provider=provider,
                        type=circuit_type,
                        status='active',
                        commit_rate=100_000_000,  # 100 Gbps, in kbps
                        description=f'Core link {a} to {z}',
                    )
                    for side, end in (('A', a), ('Z', z)):
                        CircuitTermination.objects.create(circuit=circuit, term_side=side, termination=end)
                made += 1

        self.stdout.write(
            self.style.SUCCESS(f'europe: {created_sites} site(s), {created_racks} rack(s), {made} circuit(s)')
        )

    # --------------------------------------------------------------- uplinks

    def link_uplinks(self):
        """
        Cable every top-of-rack switch to two spines in other racks, at every site that has
        more than one rack.

        Without this every cable in the demo data stops inside its own rack, so the rack
        view's "leaving the rack" list is almost always empty and the one thing it is for,
        seeing where a link actually goes, never appears. The floor's cable runs have the same
        problem one level up: a room whose cabling never crosses a cabinet draws no lines.

        A leaf and spine fabric is what a row of racks really looks like, and two spines
        rather than one is the point of it: a leaf keeps a path when a spine is lost. Every
        multi-rack site gets one, not only the busiest, or the smaller rooms stay empty and
        the view cannot be tried anywhere but at the largest site.
        """
        from django.db.models import Count

        sites = Site.objects.annotate(n=Count('racks')).filter(n__gt=1).order_by('-n')
        if not sites:
            self.stdout.write(self.style.WARNING('uplinks: no site has more than one rack'))
            return

        total, built = 0, 0
        for site in sites:
            made = self._build_fabric(site)
            if made is None:
                continue
            total += made
            built += 1
        self.stdout.write(self.style.SUCCESS(f'uplinks: {total} cable(s) across {built} site(s)'))

    def _build_fabric(self, site) -> int | None:
        """
        One leaf and spine fabric at one site, or None where there is not enough to build one.

        The first two switches by rack name become the spines. Cabling them to each other is
        skipped, since a spine is not its own uplink.
        """
        switches = list(
            Device.objects.filter(site=site, name__endswith='-tor01').select_related('rack').order_by('rack__name')
        )
        if len(switches) < 3:
            return None

        spines, leaves = switches[:2], switches[2:]
        made = 0
        for leaf in leaves:
            for spine in spines:
                # Keyed on this spine, not on "any uplink": checking for the latter stopped
                # every leaf after its first link and left the fabric single-homed, which is
                # the one property a spine pair exists to provide.
                name = f'uplink-to-{spine.rack.name.lower()}'
                if Interface.objects.filter(device=leaf, name=name).exists():
                    continue
                leaf_port = Interface.objects.filter(device=leaf, cable=None).order_by('-name').first()
                spine_port = Interface.objects.filter(device=spine, cable=None).order_by('-name').first()
                if not leaf_port or not spine_port:
                    continue
                # Renamed so the drawing and the cable list say what the link is for; an
                # uplink called et-0/0/47 tells a reader nothing.
                leaf_port.name = name
                leaf_port.save()
                made += self._cable(leaf_port, spine_port)
        return made

    # ------------------------------------------------------------------ plans

    # The name is the idempotency key: a second run finds the drawing it made last time and
    # leaves it, rather than stacking a new copy under the same racks.
    PLAN_LAYER_NAME = 'Architect plan'

    # Rooms an equipment hall actually has around its edges. Each is a label and the fraction
    # of the wall it takes, so the same drawing code serves a 5 m room and a 30 m one.
    ANCILLARY_ROOMS = (
        ('Plant room', 0.34),
        ('Store', 0.22),
        ('UPS', 0.20),
        ('Comms riser', 0.16),
        ('Loading bay', 0.28),
    )

    def add_plans(self):
        """
        Put a schematic drawing under every floor.

        Demo data has no architect's plan, and a background layer with nothing in it proves
        nothing. This is not a plan of any real building: it is walls, a few ancillary rooms
        and a door, drawn to each room's own dimensions so it lines up with the racks.

        One drawing per floor, and a different one per floor. A single shared image would have
        to be stretched to every room's proportions, which is exactly the mistake the layer's
        calibration exists to avoid, and twenty identical backgrounds would make the floors
        harder to tell apart rather than easier. The arrangement is seeded on the floor's id,
        so a re-run redraws the same building.

        A PNG, because a layer accepts raster images only (see `validate_layer_image`). Drawn
        with Pillow, which NetBox already requires, at two pixels per centimetre so it stays
        clear when the plan is zoomed in.
        """
        from netbox_spatial_lens.models import Floor, FloorLayer

        added = 0
        for floor in Floor.objects.all():
            if floor.layers.filter(name=self.PLAN_LAYER_NAME).exists():
                continue
            layer = FloorLayer(
                floor=floor,
                name=self.PLAN_LAYER_NAME,
                x=0,
                y=0,
                width=floor.width_cm,
                height=floor.depth_cm,
                opacity=0.55,
                # Well below the default, so anything added later sits on top of the drawing.
                weight=10,
            )
            layer.file.save(
                f'floor-{floor.pk}-plan.png',
                ContentFile(self._plan_png(floor.width_cm, floor.depth_cm, floor.pk)),
                save=False,
            )
            layer.save()
            added += 1
        self.stdout.write(self.style.SUCCESS(f'plans:  drawn {added}'))

    # Pixels per room centimetre, and the most pixels either side of a plan may have. Two per
    # centimetre keeps a wall sharp at the plan's usual zoom; the cap keeps a large hall's image
    # to a few hundred kilobytes.
    PLAN_PX_PER_CM = 2.0
    PLAN_MAX_PX = 4096
    PLAN_PAPER = '#f4efe6'
    PLAN_INK = '#8a7f6a'

    def _plan_png(self, width: float, depth: float, seed: int) -> bytes:
        """
        One room, in centimetres, drawn as a PNG of the room's own proportions.

        Its own `Random` rather than the module's: the plans must not depend on how many racks
        were enriched before them, or adding a step above would redraw every building.
        """
        from io import BytesIO

        from PIL import Image, ImageDraw

        rng = random.Random(seed)
        scale = min(self.PLAN_PX_PER_CM, self.PLAN_MAX_PX / max(width, depth))

        def px(value: float) -> float:
            return value * scale

        image = Image.new('RGB', (max(1, round(px(width))), max(1, round(px(depth)))), self.PLAN_PAPER)
        draw = ImageDraw.Draw(image)

        margin = min(width, depth) * 0.03
        inner_w, inner_h = width - margin * 2, depth - margin * 2
        stroke = max(1, round(px(max(3.0, min(width, depth) / 160))))

        def room(x: float, y: float, w: float, h: float) -> None:
            draw.rectangle((px(x), px(y), px(x + w), px(y + h)), outline=self.PLAN_INK, width=stroke)

        room(margin, margin, inner_w, inner_h)
        labels = []

        # A strip of ancillary rooms along one of the two short walls, filling as much of it
        # as the rooms drawn happen to take.
        rooms = rng.sample(self.ANCILLARY_ROOMS, rng.randint(2, 3))
        band = inner_h * rng.uniform(0.14, 0.2)
        at_top = rng.random() < 0.7
        band_y = margin if at_top else margin + inner_h - band
        offset = 0.0
        for name, share in rooms:
            room_w = inner_w * share
            if offset + room_w > inner_w:
                break
            room(margin + offset, band_y, room_w, band)
            labels.append((name, margin + offset, band_y, room_w, band))
            offset += room_w

        # An office in a corner of the hall, never the corner the ancillary strip is in.
        office_w, office_h = inner_w * rng.uniform(0.2, 0.3), inner_h * rng.uniform(0.14, 0.2)
        office_x = margin + (inner_w - office_w if rng.random() < 0.5 else 0)
        office_y = margin + (inner_h - office_h if at_top else 0)
        room(office_x, office_y, office_w, office_h)
        labels.append(('Office', office_x, office_y, office_w, office_h))

        # A door on the wall opposite the ancillary rooms, drawn as a gap and a swing, which
        # is what tells somebody which way round the drawing goes. The swing is a quarter circle
        # hinged at the far side of the gap, opening into the room.
        door_w = min(inner_w * 0.1, 120)
        door_x = margin + inner_w * rng.uniform(0.3, 0.6)
        door_y = margin + inner_h if at_top else margin
        draw.line((px(door_x), px(door_y), px(door_x + door_w), px(door_y)), fill=self.PLAN_PAPER, width=stroke * 3)
        hinge_x = door_x + door_w
        box = (px(hinge_x - door_w), px(door_y - door_w), px(hinge_x + door_w), px(door_y + door_w))
        draw.arc(box, *((180, 270) if at_top else (90, 180)), fill=self.PLAN_INK, width=stroke)

        for label in labels:
            self._room_label(draw, px, *label)

        out = BytesIO()
        image.save(out, format='PNG', optimize=True)
        return out.getvalue()

    def _room_label(self, draw, px, text: str, x: float, y: float, box_w: float, box_h: float) -> None:
        """
        A room's name, sized to the room, or nothing at all.

        A fixed size cannot serve both a 30 m hall and a 2 m comms closet: on the small one the
        words run across three rooms and the drawing is worse than blank. So the size comes
        from the box, and a box too small to hold the word legibly goes unlabelled.
        """
        from PIL import ImageFont

        # 0.55 em per character is about right for a sans-serif at these sizes.
        size = min(box_h * 0.4, box_w * 0.9 / (len(text) * 0.55))
        if size < 12:
            return
        font = ImageFont.load_default(size=max(1, round(px(size))))
        draw.text((px(x + box_w / 2), px(y + box_h / 2)), text, fill=self.PLAN_INK, font=font, anchor='mm')
