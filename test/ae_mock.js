/*
 * A mock After Effects, enough to run the adapters under node.
 *
 * The adapters are the one part of the AE side that must touch the host, so
 * they cannot be tested the way `ae/rotobridge_core.jsx` is. This is the next
 * best thing: a stand-in that answers the same calls, counts them, and lets the
 * export and import scripts run end to end with no application present.
 *
 * It is a mock, not a simulator. What it faithfully reproduces is the shape of
 * the API - `valueAtTime`, `sourcePointToComp` with no time parameter, mask
 * properties by matchName, the `Shape` object feather points live on - and an
 * exactly affine layer transform, which is the assumption the export's fast
 * path rests on.
 *
 * Between keys it interpolates only what has been measured (LINEAR, probe run 6
 * section H) or is definitional (HOLD, and no extrapolation past the ends).
 * BEZIER raises: its shape depends on influence and speed in a way nothing here
 * has measured, and a plausible-looking guess would make the drift pass appear
 * to work under test while doing nothing in the host. See `makeProp`.
 *
 * The call counters are load-bearing, not diagnostics. Two of this project's
 * decisions - the frame-major loop and the derived affine - are performance
 * requirements written into acceptance criterion 11, and a performance
 * requirement that nothing checks is a comment. `timeAssignments` and
 * `pointCalls` turn both into assertions.
 */

function CompItem() {}

function makeShape(spec) {
    return {
        vertices: spec.vertices,
        inTangents: spec.inTangents,
        outTangents: spec.outTangents,
        closed: spec.closed === undefined ? true : spec.closed,
        featherSegLocs: spec.featherSegLocs || [],
        featherRelSegLocs: spec.featherRelSegLocs || [],
        featherRadii: spec.featherRadii || [],
        featherTypes: spec.featherTypes || [],
        featherInterps: [],
        featherTensions: [],
        featherRelCornerAngles: []
    };
}

var LINEAR = 6612, BEZIER = 6613, HOLD = 6614;

function KeyframeEase(speed, influence) {
    this.speed = speed;
    this.influence = influence;
}

function defaultEase() { return new KeyframeEase(0, 16.667); }

function lerp(a, b, u) {
    /* Component-wise, through numbers, arrays, arrays of arrays and the Shape
     * object a mask path evaluates to. */
    if (typeof a === "number") { return a + (b - a) * u; }
    if (Object.prototype.toString.call(a) === "[object Array]") {
        var out = [];
        for (var i = 0; i < a.length; i++) { out[i] = lerp(a[i], b[i], u); }
        return out;
    }
    return makeShape({
        vertices: lerp(a.vertices, b.vertices, u),
        inTangents: lerp(a.inTangents, b.inTangents, u),
        outTangents: lerp(a.outTangents, b.outTangents, u),
        closed: a.closed,
        /* Where a feather point sits is authored, not interpolated: the
         * importer pins one per vertex at the start of its own segment on
         * every frame, so only the radius moves. */
        featherSegLocs: a.featherSegLocs,
        featherRelSegLocs: a.featherRelSegLocs,
        featherRadii: lerp(a.featherRadii, b.featherRadii, u),
        featherTypes: a.featherTypes
    });
}

function makeProp(valueFn, seed) {
    /* Reads come from `valueFn` until something writes a key, after which the
     * keys are the value. That is enough for an import to build a mask and an
     * export to read it straight back - the round trip the mock exists for.
     *
     * Between keys it interpolates **only what has been measured or is
     * definitional**, and raises otherwise:
     *
     * - Two LINEAR sides interpolate straight. Probe run 6 section H measured
     *   it on a real mask path: the midpoint of [100,100] and [500,200] read
     *   back [300,150].
     * - A HOLD outgoing side freezes the segment. That is what hold means, and
     *   spec section 10.2 states it for both hosts.
     * - Outside the key range the nearest key's value stands, which is After
     *   Effects' own default - it does not extrapolate.
     * - **BEZIER raises.** Its shape depends on influence and speed in a way
     *   nothing here has measured, and a plausible-looking guess would make the
     *   drift pass appear to work under test while doing nothing in the host.
     *   Tests that need a measured segment author linear keys; tests that need
     *   bezier keys leave no gap for the pass to measure.
     */
    var keys = [];   // [{t, value, inType, outType, inEase, outEase}], ascending
    var EPS = 1e-9;

    function find(t) {
        for (var i = 0; i < keys.length; i++) {
            if (Math.abs(keys[i].t - t) < EPS) { return i; }
        }
        return -1;
    }

    function between(t) {
        if (t <= keys[0].t) { return keys[0].value; }
        if (t >= keys[keys.length - 1].t) { return keys[keys.length - 1].value; }
        var lo = 0;
        while (lo + 1 < keys.length && keys[lo + 1].t < t) { lo += 1; }
        var a = keys[lo], b = keys[lo + 1];
        if (a.outType === HOLD) { return a.value; }
        if (a.outType !== LINEAR || b.inType !== LINEAR) {
            throw new Error("ae_mock only interpolates LINEAR and HOLD; got out="
                            + a.outType + " in=" + b.inType + " at t=" + t);
        }
        return lerp(a.value, b.value, (t - a.t) / (b.t - a.t));
    }

    var prop = {
        get numKeys() { return keys.length; },
        get value() { return keys.length ? keys[0].value : valueFn(0); },
        _keys: keys,

        valueAtTime: function (t) {
            if (!keys.length) { return valueFn(t); }
            var i = find(t);
            return i === -1 ? between(t) : keys[i].value;
        },

        setValueAtTime: function (t, value) {
            var i = find(t);
            if (i > -1) { keys[i].value = value; return; }
            keys.push({ t: t, value: value, inType: LINEAR, outType: LINEAR,
                        inEase: defaultEase(), outEase: defaultEase() });
            keys.sort(function (a, b) { return a.t - b.t; });
        },

        setValue: function (value) { prop.setValueAtTime(0, value); },
        keyTime: function (i) { return keys[i - 1].t; },
        keyValue: function (i) { return keys[i - 1].value; },
        setInterpolationTypeAtKey: function (i, inType, outType) {
            keys[i - 1].inType = inType;
            keys[i - 1].outType = outType === undefined ? inType : outType;
        },
        keyInInterpolationType: function (i) { return keys[i - 1].inType; },
        keyOutInterpolationType: function (i) { return keys[i - 1].outType; },
        setTemporalEaseAtKey: function (i, inEase, outEase) {
            /* After Effects forces the key to BEZIER when an ease is set, and
             * the adapter relies on that being undone by the
             * `setInterpolationTypeAtKey` it makes afterwards. Reproducing the
             * forcing here is what makes that ordering testable. */
            keys[i - 1].inEase = inEase[0];
            keys[i - 1].outEase = (outEase === undefined ? inEase : outEase)[0];
            keys[i - 1].inType = BEZIER;
            keys[i - 1].outType = BEZIER;
        },
        keyInTemporalEase: function (i) { return [keys[i - 1].inEase]; },
        keyOutTemporalEase: function (i) { return [keys[i - 1].outEase]; }
    };

    for (var k = 0; k < (seed || []).length; k++) {
        var spec = seed[k];
        keys.push({
            t: spec.t,
            value: spec.value,
            inType: spec.inType === undefined ? LINEAR : spec.inType,
            outType: spec.outType === undefined ? LINEAR : spec.outType,
            inEase: spec.inEase || defaultEase(),
            outEase: spec.outEase || defaultEase()
        });
    }
    keys.sort(function (a, b) { return a.t - b.t; });
    return prop;
}

function makeMask(spec) {
    var props = {
        "ADBE Mask Shape": makeProp(spec.pathAt, spec.pathKeys),
        "ADBE Mask Feather": makeProp(spec.featherAt
            || function () { return [0, 0]; }),
        "ADBE Mask Opacity": makeProp(spec.opacityAt
            || function () { return 100; }),
        "ADBE Mask Offset": makeProp(spec.expansionAt
            || function () { return 0; })
    };
    return {
        name: spec.name,
        maskMode: spec.maskMode === undefined ? 6813 : spec.maskMode,
        inverted: !!spec.inverted,
        maskFeatherFalloff: spec.falloff === undefined ? 7213 : spec.falloff,
        property: function (matchName) { return props[matchName]; },
        /* The host exposes the common ones as members as well as by matchName,
         * and probe section E2 used `mask.maskFeather` that way. */
        get maskFeather() { return props["ADBE Mask Feather"]; },
        get maskOpacity() { return props["ADBE Mask Opacity"]; }
    };
}

function makeLayer(host, spec) {
    /* The transform is a real affine - anchor, scale, rotation, position, in
     * After Effects' own composition order - because the export derives one
     * from three probes and then trusts it. A mock that returned the identity
     * would let a broken derivation pass. */
    var xf = spec.transform || {};
    var anchor = xf.anchor || [0, 0];
    var scale = xf.scale || [1, 1];
    var rotation = (xf.rotation || 0) * Math.PI / 180;
    var position = xf.position || [0, 0];

    function toComp(p) {
        host.pointCalls += 1;
        var x = (p[0] - anchor[0]) * scale[0];
        var y = (p[1] - anchor[1]) * scale[1];
        return [position[0] + x * Math.cos(rotation) - y * Math.sin(rotation),
                position[1] + x * Math.sin(rotation) + y * Math.cos(rotation)];
    }

    function toSource(p) {
        host.pointCalls += 1;
        var x = p[0] - position[0];
        var y = p[1] - position[1];
        var rx = x * Math.cos(-rotation) - y * Math.sin(-rotation);
        var ry = x * Math.sin(-rotation) + y * Math.cos(-rotation);
        return [rx / scale[0] + anchor[0], ry / scale[1] + anchor[1]];
    }

    /* The transform group, with keys where a test asked for them. Only the
     * key TIMES matter to the export - the transform itself is `toComp` above,
     * which is the thing the geometry actually goes through - so a keyed
     * property here holds times and nothing else. */
    var transform = {
        _props: {},
        property: function (matchName) {
            return this._props[matchName] || null;
        }
    };
    var wantKeys = spec.transformKeys || {};
    for (var name in wantKeys) {
        if (!Object.prototype.hasOwnProperty.call(wantKeys, name)) { continue; }
        transform._props[name] = makeProp(
            function () { return 0; },
            wantKeys[name].map(function (t) { return { t: t, value: 0 }; }));
    }

    var masks = (spec.masks || []).map(makeMask);
    var parade = {
        numProperties: masks.length,
        property: function (i) { return masks[i - 1]; },
        addProperty: function (matchName) {
            if (matchName !== "ADBE Mask Atom") {
                throw new Error("unexpected addProperty(" + matchName + ")");
            }
            var made = makeMask({
                name: "Mask " + (masks.length + 1),
                /* A mask with no key yet reads as an empty shape, which is
                 * what a freshly added one is. */
                pathAt: function () {
                    return makeShape({ vertices: [], inTangents: [],
                                       outTangents: [] });
                }
            });
            masks.push(made);
            parade.numProperties = masks.length;
            return made;
        }
    };

    return {
        name: spec.name,
        index: spec.index,
        threeDLayer: !!spec.threeD,
        parent: spec.parent || null,
        property: function (matchName) {
            if (matchName === "ADBE Mask Parade") { return parade; }
            if (matchName === "ADBE Transform Group") { return transform; }
            throw new Error("no property " + matchName);
        },
        sourcePointToComp: toComp,
        compPointToSource: toSource,
        _masks: masks
    };
}

function makeComp(host, spec) {
    var comp = new CompItem();
    comp.name = spec.name || "Comp 1";
    comp.width = spec.width || 1920;
    comp.height = spec.height || 1080;
    comp.pixelAspect = spec.pixelAspect || 1;
    comp.frameRate = spec.frameRate || 24;
    comp.displayStartTime = spec.displayStartTime || 0;
    comp.workAreaStart = spec.workAreaStart || 0;
    comp.workAreaDuration = spec.workAreaDuration;
    comp.duration = spec.duration || comp.workAreaDuration;

    var layers = (spec.layers || []).map(function (s, i) {
        return makeLayer(host, Object.assign({ index: i + 1 }, s));
    });
    comp.numLayers = layers.length;
    comp.layer = function (i) { return layers[i - 1]; };
    comp.layers = {
        addSolid: function (colour, name, w, h, aspect) {
            /* An identity transform, which is what a fresh solid has - so the
             * comp-to-layer conversion on import is a no-op unless a test
             * deliberately selects a transformed layer instead. */
            var made = makeLayer(host, { name: name, index: layers.length + 1,
                                         masks: [] });
            layers.push(made);
            comp.numLayers = layers.length;
            return made;
        }
    };
    comp.selectedLayers = spec.selected === undefined
        ? layers.slice(0) : spec.selected.map(function (i) { return layers[i]; });
    comp._layers = layers;

    var time = 0;
    Object.defineProperty(comp, "time", {
        get: function () { return time; },
        set: function (v) { host.timeAssignments += 1; time = v; }
    });
    return comp;
}

function install(spec) {
    /* Put a mock host into the globals the adapters reach for, and return the
     * handle the test asserts against. */
    var host = {
        timeAssignments: 0,
        pointCalls: 0,
        written: null,
        alerts: [],
        // Checked against undefined, not falsiness: a test that cancels the
        // dialog passes an explicit null, and `||` would hand it the default.
        savePath: spec.savePath === undefined ? "/tmp/out.rbj" : spec.savePath,
        openPath: spec.openPath === undefined ? "/tmp/in.rbj" : spec.openPath,
        readable: spec.readable || "",
        prompts: [],
        /* Consumed in order by `prompt`; an empty list takes every default,
         * which is the path an artist gets by pressing return. */
        answers: (spec.answers || []).slice(0)
    };

    host.comp = makeComp(host, spec);

    global.CompItem = CompItem;
    global.Shape = function () {
        this.vertices = [];
        this.inTangents = [];
        this.outTangents = [];
        this.closed = true;
        this.featherSegLocs = [];
        this.featherRelSegLocs = [];
        this.featherRadii = [];
        this.featherTypes = [];
        this.featherInterps = [];
        this.featherTensions = [];
        this.featherRelCornerAngles = [];
    };
    global.KeyframeInterpolationType = { LINEAR: 6612, BEZIER: 6613,
                                         HOLD: 6614 };
    global.KeyframeEase = KeyframeEase;
    global.MaskMode = { NONE: 6812, ADD: 6813, SUBTRACT: 6814,
                        INTERSECT: 6815, LIGHTEN: 6816, DARKEN: 6817,
                        DIFFERENCE: 6818 };
    global.prompt = function (message, preset) {
        host.prompts.push(message);
        if (host.answers.length) { return host.answers.shift(); }
        return preset;
    };
    global.app = {
        version: spec.appVersion || "25.6x101",
        project: { activeItem: host.comp },
        beginUndoGroup: function () {},
        endUndoGroup: function () {}
    };
    global.alert = function (message) { host.alerts.push(message); };

    function FakeFile(path) {
        this.fsName = path;
        this.name = String(path).split("/").pop();
        this.encoding = "";
    }
    FakeFile.prototype.open = function (mode) {
        this._mode = mode;
        return true;
    };
    FakeFile.prototype.write = function (text) { host.written = text; };
    FakeFile.prototype.read = function () { return host.readable || ""; };
    FakeFile.prototype.close = function () { return true; };
    FakeFile.saveDialog = function () {
        return host.savePath ? new FakeFile(host.savePath) : null;
    };
    FakeFile.openDialog = function () {
        return host.openPath ? new FakeFile(host.openPath) : null;
    };
    global.File = FakeFile;

    return host;
}

module.exports = { install: install, makeShape: makeShape,
                   CompItem: CompItem, KeyframeEase: KeyframeEase };
